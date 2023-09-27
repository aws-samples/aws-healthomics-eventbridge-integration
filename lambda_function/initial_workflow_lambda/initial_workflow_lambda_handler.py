import boto3
import os
import botocore.exceptions
import json
import logging
import uuid
from collections import defaultdict

OUTPUT_S3_LOCATION = os.environ['OUTPUT_S3_LOCATION']    
OMICS_ROLE = os.environ['OMICS_ROLE']        
WORKFLOW_ID = os.environ['WORKFLOW_ID']
ECR_REGISTRY = os.environ['ECR_REGISTRY']
LOG_LEVEL = os.environ['LOG_LEVEL']

omics = boto3.client('omics')
s3 = boto3.client('s3')

# enable logging 
logging.basicConfig(level=LOG_LEVEL)
logging.info("Initial workflow lambda Function started.")

def localize_s3_file(bucket, _key, local_file):
    s3_client = boto3.client('s3')

    try:
        s3_client.download_file(
            Bucket=bucket,
            Key=_key,
            Filename=local_file
        )
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            logging.error("The object does not exist.")
        else:
            raise
    return

def build_input_payload_for_r2r_gatk_fastq2vcf(sample_manifest_csv):
    """
    Function specific to the HealthOmics Ready2Run workflow
    GATK-BP Germline fq2vcf for 30x genome
    """
    # Validate if sample manifest in acceptable format
    """
    Example CSV schema

    sample_name,read_group,fastq_1,fastq_2,platform
    SampleX,RG1,s3://path/to/SampleX/RG1/001_R1.fastq.gz,s3://path/to/SampleX/RG1/001_R2.fastq.gz,solid
    SampleX,RG1,s3://path/to/SampleX/RG1/002_R1.fastq.gz,s3://path/to/SampleX/RG1/002_R2.fastq.gz,solid
    SampleX,RG2,s3://path/to/SampleX/RG2/001_R1.fastq.gz,s3://path/to/SampleX/RG2/001_R2.fastq.gz,solid
    SampleX,RG2,s3://path/to/SampleX/RG2/002_R1.fastq.gz,s3://path/to/SampleX/RG2/002_R2.fastq.gz,solid
    """
    
    with open(sample_manifest_csv) as smc:
        contents = smc.readlines()
    
    header = contents[0].strip()
    if header != "sample_name,read_group,fastq_1,fastq_2,platform":
        raise Exception("Invalid sample manifest CSV header")
    
    # prepare workflow input payload per sample
    samples = defaultdict(dict)
    for _line in contents[1:]:
        sample_name,read_group,fastq_1,fastq_2,platform = _line.strip().split(',')
        if read_group not in samples[sample_name]:
            samples[sample_name][read_group] = {}
        samples[sample_name][read_group]['fastq_1'] = fastq_1
        samples[sample_name][read_group]['fastq_2'] = fastq_2
        samples[sample_name][read_group]['platform'] = platform
    
    samples_params = []
    for _sample, _obj in samples.items():
        logging.info(f"Creating input payload for sample: {_sample}")
        _params = {}
        _params['sample_name'] = _sample
        _params['fastq_pairs'] = []
        for _rg, _details in _obj.items():
            _params['fastq_pairs'].append({
                'read_group': _rg,
                'fastq_1': _details['fastq_1'],
                'fastq_2': _details['fastq_2'],
                'platform': _details['platform']
            })
        samples_params.append(_params)

    return samples_params

# Lambda function triggered by S3 event
# and launch of initial workflow
def handler(event, context):
    logging.debug("Received event: " + json.dumps(event, indent=2))

    # ensure s3 events only holds 1 Records entry --> 'events' can hold >1 record for S3 Batch Operations
    num_upload_records = len(event["Records"])
    if num_upload_records == 1:
        # get event info
        filename = event['Records'][0]['s3']['object']['key']
        bucket_arn = event["Records"][0]["s3"]["bucket"]["arn"]
        bucket_name = event["Records"][0]["s3"]["bucket"]["name"]
        logging.info(f"Processing {filename} in {bucket_arn}")
    elif num_upload_records == 0:
        raise Exception("No file detected for analysis!")
    else:
        raise Exception("Multiple s3 files in event not yet suppported")
    #TODO: implement processing of multiple files in future version 

    # dowload manifest CSV
    local_file = "/tmp/sample_manifest.csv"
    localize_s3_file(bucket_name, filename, local_file)
    logging.info(f"Downloaded manifest CSV to: {local_file}")

    multi_sample_params = build_input_payload_for_r2r_gatk_fastq2vcf(local_file)
    error_count = 0
    for _item in multi_sample_params:
        _samplename = _item['sample_name']
        logging.info(f"Starting workflow for sample: {_samplename}")
        run_name = f"Sample_{_samplename}_" + str(uuid.uuid4())
        try:
            response = omics.start_run(
                workflowType='READY2RUN',
                workflowId=WORKFLOW_ID,
                name=run_name,
                roleArn=OMICS_ROLE,
                parameters=_item,
                outputUri=OUTPUT_S3_LOCATION,
                logLevel='ALL',
                tags={
                        "SOURCE": "LAMBDA_INITIAL_WORKFLOW",
                        "RUN_NAME": run_name,
                        "SAMPLE_MANIFEST": f"s3://{bucket_name}/{filename}"
                    }     
            )
            logging.info(f"Workflow response: {response}")
        except botocore.exceptions.ClientError as ce:
            logging.error( "boto3 client error : " + ce.__str__())
            error_count += 1
        except Exception as e:
            logging.error( "unknown error : " + e.__str__())
            error_count += 1
        

    if error_count > 0:
        raise Exception("Error launching some workflows, check logs")
    return
