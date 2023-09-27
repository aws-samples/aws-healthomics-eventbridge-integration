import boto3
import os
from botocore.exceptions import ClientError
import logging
import uuid

OUTPUT_S3_LOCATION = os.environ['OUTPUT_S3_LOCATION']    
OMICS_ROLE = os.environ['OMICS_ROLE']        
WORKFLOW_ID = os.environ['WORKFLOW_ID']
UPSTREAM_WORKFLOW_ID = os.environ['UPSTREAM_WORKFLOW_ID']
ECR_REGISTRY = os.environ['ECR_REGISTRY']
VEP_SPECIES = os.environ['SPECIES']
VEP_DIR_CACHE = os.environ['DIR_CACHE']
VEP_CACHE_VERSION = os.environ['CACHE_VERSION']
VEP_GENOME = os.environ['GENOME']
LOG_LEVEL = os.environ['LOG_LEVEL']

omics = boto3.client('omics')
s3 = boto3.client('s3')

# enable logging 
logging.basicConfig(level=LOG_LEVEL)
logging.info("Initial workflow lambda Function started.")

# Lambda function triggered by EventBridge event
# from Omics successful run of initial workflow
# and submit the next workflow 
# Example event
"""{
    "version": "0",
    "id": "4c338660-3a89-69ad-40d5-aakjhfjkaf",
    "detail-type": "Run Status Change",
    "source": "aws.omics",
    "account": "0000000000",
    "time": "2023-07-28T06:19:39Z",
    "region": "us-west-2",
    "resources":
    [
        "arn:aws:omics:us-west-2:0000000000:run/1111111"
    ],
    "detail":
    {
        "omicsVersion": "1.0.0",
        "arn": "arn:aws:omics:us-west-2:0000000000:run/1111111",
        "status": "PENDING"
    }
}
"""
def split_s3_path(s3_path):
    path_parts=s3_path.replace("s3://","").split("/")
    bucket=path_parts.pop(0)
    key="/".join(path_parts)
    return bucket, key
    
def handler(event, context, omics_client=omics, s3_client=s3):
    AWS_ACCOUNT_ID = boto3.client('sts').get_caller_identity()['Account']

    logging.debug(event)

    # check if event is valid
    event_detail_type = event['detail-type']
    if event_detail_type != 'Run Status Change':
        raise("Unknown event triggered this Lambda, unable to process")
    
    # Get the omics run ID
    omics_run_id = event['detail']['arn'].split('/')[-1]
    logging.info(f"Omics Run ID: {omics_run_id}")
    
    # Get the omics run details
    omics_workflow_run  = omics_client.get_run(id=omics_run_id)
    omics_workflowId = omics_workflow_run['workflowId']
    if omics_workflowId == UPSTREAM_WORKFLOW_ID:
        logging.info(f"Omics Workflow ID: {omics_workflowId} matched, continue processing")
    else:
        logging.info(f"ERROR! Expected input from workflow ({UPSTREAM_WORKFLOW_ID}), but received input from workflow ({omics_workflowId}) ")
        return {
            'statusCode': 200,
            'runStatus': "Lambda function finished successfully. No HealthOmics workflow started.",
            'runIds': []
        }
        

    # list all files in output bucket
    run_output_path = f"{omics_workflow_run['outputUri']}/{str(omics_run_id)}"
    s3bucket, s3key = split_s3_path(run_output_path)
    paginator = s3_client.get_paginator('list_objects')
    page_iterator = paginator.paginate(Bucket=s3bucket, Prefix=s3key)

    # find .vcf.gz file in directory
    found = False
    vcf_file = None
    for page in page_iterator:
        if found:
            break
        for obj in page['Contents']:
            if obj['Key'].endswith('.vcf.gz'):
                vcf_file =f"s3://{s3bucket}/{obj['Key']}"
                found = True
                break
    if not found:
        raise Exception("no .vcf.gz file found in output directory, exiting")

    sample_name = vcf_file.split('/')[-1].split('.')[0]
    run_name = f"VEP Sample {sample_name} " + str(uuid.uuid4())

    workflow_params = {
        "id": sample_name,
        "vcf": vcf_file,
        "vep_species": VEP_SPECIES,
        "vep_genome": VEP_GENOME,
        "ecr_registry": ECR_REGISTRY,
        "vep_cache": VEP_DIR_CACHE,
        "vep_cache_version": VEP_CACHE_VERSION
    }

    try:
        run = omics_client.start_run(
            workflowType='PRIVATE',
            workflowId=str(WORKFLOW_ID),
            name=run_name,
            roleArn=OMICS_ROLE,
            parameters=workflow_params,
            logLevel="ALL",
            outputUri=OUTPUT_S3_LOCATION, 
            tags={
                "SOURCE": "LAMBDA_POST_INITIAL_WORKFLOW",
                "PARENT_WORKFLOW_ID": UPSTREAM_WORKFLOW_ID,
                "PARENT_WORKFLOW_RUN_ID": omics_run_id,
                "SAMPLE_NAME": sample_name
            }
        )
        # get relevant run details
        run_id = run['id']
        logging.info(f"Successfully started HealthOmics Run ID: {run_id} for sample: {sample_name}")
    except ClientError as ce:
        raise Exception( "boto3 client error : " + ce.__str__())
    except Exception as e:
        raise Exception( "unknown error : " + e.__str__())

    return {
        "statusCode": 200,
        "statusMessage": "Workflows launched successfully"
    }