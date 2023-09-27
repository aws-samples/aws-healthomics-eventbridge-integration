
# Solution Overview


AWS HealthOmics workflows allows customers to process their genomics or other multi-omic data either by bringing their own workflows or running existing Ready2Run workflows. <insert blog link here look at other README> Often, customers want to have automation in place to launch workflows automatically, trigger a new process, such as another AWS HealthOmics workflow, after successful completion of the first workflow and notify users in case of workflow failure. AWS HealthOmics has an integration with Amazon EventBridge which enables customers to build a production scale, fully automated and event-driven solution on AWS. This solution demonstrates how we can automatically launch an AWS HealthOmics workflow upon file upload, use EventBridge to launch a second workflow on successful completion of the first workflow and notify a user (or group) on failure via Amazon SNS. This repository includes sample code with infrastructure as code (IaC) and sample data that can be used by customers to deploy this solution in their own accounts. The solution leverages various AWS services such as HealthOmics, EventBridge, S3, IAM, Lambda, SNS and ECR to create end-to-end "omics" data processing pipelines. The solution automatically starts a workflow run on data upload, notifies users of workflow failures and continues downstream processing with another workflow on successful completion of the first workflow. This automation enables users to focus on scientific research instead of the infrastructure and reduces operational overhead.


# Architecture 

The diagram below shows the high-level architecture for the solution including the end-to-end flow of data.

![image](./assets/omics-eventbridge-architecture.png?raw=true "Architecture")


# Well-Architected

The solution was built using the 5 [AWS Well-Architected pillars](https://aws.amazon.com/architecture/well-architected) - Operational Excellence, Security, Reliability, Cost Optimization, and Performance Efficiency.

**Operational Excellence**

* Infrastructure-as-Code (IaC) with [AWS Cloud Development Kit (CDK)](https://aws.amazon.com/cdk/) for ease of deployment, change management, and compliance.
* AWS HealthOmics, a managed service, to simplify workflow infrastructure and orchestration.

**Security**

* Encrypt S3 buckets with sequence data (inputs and outputs).
* Use least-privilege access with Identity and Access Management (IAM).
* AWS HealthOmics workflow operates in a private environment with no incoming or outgoing access to the public internet. 
* Ensure that S3 data is uploaded with encryption in transite best practices.

**Reliability**

* Ability to scale using Lambda functions, HealthOmics workflows, and S3.
* Ability to capture failures and push-based notifications enable operations teams to act on failures as soon as they occur and minimize delays in data analysis. 

**Performance Efficiency**

* Event-driven automation using EventBridge to run the next action as soon as previous action is completed.
* Optimized HealthOmics Ready2Run workflows
* Ability to get performant instances based on workflow requirements with HealthOmics Private workflows.

**Cost Optimization**

* Use a managed service, AWS HealthOmics, which reduces resources spent on managing and securing workflow management applications and associated infrastructure, thus reducing total cost of ownership (TCO). 
* Use a Ready2Run workflow where applicable to reduce developer time building, testing, optimizing, and maintaining bioinformatics workflows. 
* To further optimize costs for storage of sequence data, customers can store the FASTQ files generated in AWS HealthOmics sequence stores. Data stored in these stores can be used as input to HealthOmics workflows, similar to S3, while offering better cost savings.


# Solution Setup

## Prerequisites 

The following prerequisites are needed to deploy and test the solution:

* Access to an AWS account and relevant permissions to create/use the following services:
    * AWS Lambda, AWS HealthOmics, Amazon S3, Amazon Eventbridge, AWS IAM, Amazon SNS, Amazon ECR, Amazon CloudWatch Logs, AWS KMS, Cloud9 (optional)
* Node.js and npm installed
* Python 3 installed
* AWS CLI installed and configured
* AWS CDK CLI installed


### Option 1 : Use Cloud9 

Create a Cloud9 Instance to run this solution (https://catalog.us-east-1.prod.workshops.aws/workshops/d93fec4c-fb0f-4813-ac90-758cb5527f2f/en-US/start/cloud9)

### Option 2 : Using your desktop

You can set up the pre-requisites on your local workstation/laptop as well. Look at the requirements.txt file in https://gitlab.aws.dev/omics/omics-event-bridge-int/-/blob/main/requirements.txt
(will change when uploaded to GitHub)

## Implementation

This solution uses IaC with CDK and Python to deploy and manage resources in the cloud. The following steps show how to initialize and deploy the solution:

### Initial Setup

Open Cloud9 environment or local environment and run the commands below to initialize CDK pipeline for deployment.



[IMPORTANT!]
> **Check for availability of all services such as HealthOmics in the region before you take the steps below. Use the following resource to confirm: https://aws.amazon.com/about-aws/global-infrastructure/regional-product-services/**

    python -m pip install aws-cdk-lib
    npm install -g aws-cdk
    npm install -g aws-cdk --force
    cdk bootstrap aws://<ACCOUNTID>/<AWS-REGION>   # do this if your account hasn't been bootstraped
    cdk --version

* Make sure to replace "ACCOUNTID" placeholder with actual account number
* Replace “AWS-REGION” with a valid AWS region where you plan to deploy the solution. e.g. us-east-1 

### Create Infrastructure

Run the commands below to clone and deploy the HealthOmics-EventBridge integration solution using CDK. Running "cdk deploy" creates AWS CloudFormation templates to deploy the infrastructure.


    git clone <github>
    cd <proj-dir>
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    cdk synth
    cdk deploy --all


The deployment creates the following resources:

* Explore the console to validate the following resources are created:
  * Amazon S3 buckets - an *INPUT* bucket to store inputs and an *OUTPUT* bucket where the HealthOmics workflows upload outputs.
  * AWS Lambda functions - an *initial* Lambda function to launch the first HealthOmics workflow and a *post-initial* Lambda function to launch the second HealthOmics workflow.
  * AWS HealthOmics private workflow - *vep* - This is a private workflow whose Docker image gets built and stored in Amazon ECR followed by creating the workflow with HealthOmics.
  * Amazon SNS topic - *-workflow_failure_notification* topic to receieve failure notifications from HealthOmics workflows
  * Amazon EventBridge rules - rule with source *HealthOmics workflow run* and target *post-initial lambda function*
  * IAM roles and policies - multiple IAM roles for lambda functions and HealthOmics workflow runs to enable least-privileged access to appropriate resources.

[NOTE!]
You can verify that these resources were created by navigating the AWS console after successful CDK deployment.

## Solution Walkthrough & Testing


### Subscribe to workflow failure SNS notification

Before you test the solution, you need to subscribe to the Amazon SNS topic (name should be *_workflow_status_topic) with your email address to receive email notifications in case the HealthOmics workflow runs fail. Follow instructions here on how to subscribe: https://docs.aws.amazon.com/sns/latest/dg/sns-create-subscribe-endpoint-to-topic.html 

[NOTE!]
> Confirm your subscription using the email received right after the above step.

### Create and Upload a Sample Manifest CSV file

When a batch of samples’ sequence data is generated and requires analysis using bioinformatics workflows, a user or an existing system, such as a Laboratory Information Management System (LIMS), generates a manifest, also referred to as a sample sheet, that describes the samples and associated metadata such as sample names and sequencing instrument related metadata. Below is an example CSV used for testing in this solution:

```
sample_name,read_group,fastq_1,fastq_2,platform
NA12878,Sample_U0a,s3://aws-genomics-static-{aws-region}/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R1_001.fastq.gz,s3://aws-genomics-static-{aws-region}/omics-tutorials/data/fastq/NA12878/Sample_U0a/U0a_CGATGT_L001_R2_001.fastq.gz,illumina
```
We will be using publicly available test FASTQ files hosted in public AWS test data buckets. You can use your own FASTQ files in your S3 buckets as well. 

1. Use the provided test file in the solution code: *"workflows/vep/test_data/sample_manifest_with_test_data.csv"*. Replace the {aws-region} string in the file contents with the AWS region in which you have deployed the solution. The publicly available FASTQ data referenced in the CSV is available in all the regions where AWS HealthOmics is available.
2. Upload this file to the input bucket created by the solution under the “fastq” prefix

```
aws s3 cp sample_manifest_with_test_data.csv s3://<INPUTBUCKET>/fastqs/
```

### Automated launch of the HealthOmics workflow – GATK-BP Germline fq2vcf for 30x genome

On file upload, The initial AWS Lambda function is launched and it performs the following steps:

* Checks for validity of sample manifest file;
* Prepares inputs based on event and pre-configured data; and
* Launches the workflow – GATK-BP Germline fq2vcf for 30x genome – using a HealthOmics API call.

You can navigate to the AWS HealthOmics console and confirm the launch of the workflow under "Runs"

### Post GATK-BP Germline fq2vcf workflow

AWS HealthOmics is integrated with Amazon EventBridge which enables downstream event-driven automation. We have set up two rules within EventBridge. 

1. On successful completion of the "GATK-BP Germline fq2vcf for 30x genome" workflow, a Lambda function - post initial - is triggered to launch the next HealthOmics workflow – VEP – using the output (i.e. gVCF file) of the previous workflow. The outputs of the previous workflow run are BAM and gVCF files, which can be verified by inspecting the output S3 bucket and prefix for that workflow run.
   
2. On workflow failure, an Amazon SNS topic is the rule target. If you have subscribed to the SNS topic, you should receive a failure notification to your email that you used.

Example event created by AWS HealthOmics on workflow run status change:

    {
        "version": "0",
        "id": "64ca0eda-9751-dc55-c41a-1bd50b4fc9b7",
        "detail-type": "Workflow Status Change",
        "source": "aws.omics",
        "account": "123456789012",
        "time": "2018-07-01T17:53:06Z",
        "region": "us-west-2",
        "resources": [],
        
        "detail": {
            "omicsVersion": "1.0.0",
            "arn": "arn:aws:omics:us-west-2:123456789012:workflow/123456",
            "status": "FAILED"
        }
    }

### Automated launch of the AWS HealthOmics workflow – VEP
The successful completion of the "GATK-BP Germline fq2vcf for 30x genome" workflow triggers the post-initial Lambda function that:

* Verifies the outputs of this workflow;
* Prepares the input payload for the next workflow, VEP, based on event and pre-configured data; and
* Launches the workflow – VEP – using the HealthOmics API.

 
### Post VEP workflow 
Upon successful workflow completion of the VEP workflow run, outputs of the workflow are uploaded to the output S3 location. Similar to the GATK-BP Germline fq2vcf workflow, if the workflow fails or times out, the configured EventBridge rule triggers an SNS notification to notify the email distribution list so that appropriate actions can be taken by users. 

--------------
## Clean up

* Empty the S3 input and output buckets before cleaning up the solution with IaC.
* Execute the commands shown below to delete the resources created by the solution.

    cdk destroy 

## Cost

The cost of running this solution is based on the usage of AWS services. Users will be charged based on the processing time for services (ex: HealthOmics workflow) and for storage (ex: S3).

* Amazon S3
    * With sample data approximately 1 GB ≈ $0.023 
* AWS HealthOmics
    * HealthOmics GATK-BP Germline fq2vcf workflow: $10 per run
    * Private VEP workflow with test data included: $0.17
* AWS Lambda
    * Initial lambda function memory: 512 MB → $0.0000000083 per ms
    * Post-initial lambda function memory: 128 MB → $0.0000000021 per ms
* Amazon EventBridge
    * Falls within the AWS Free Tier.
* Amazon SNS
    * Falls within the AWS Free Tier.

For example: 
If you have a workflow that uses the sample data put into S3, run the architecture once with no failures it will cost approximately $10.59.


## Changes

Please review the file: [CHANGES](./CHANGES.md) for a list of revisions made to this solution.

## License and Citations

[LICENSE](./LICENSE)

[Third Party Licenses](./THIRD-PARTY-LICENCES)

[Citations](./CITATIONS.md)

## Contributing

Please review the file: [CONTRIBUTING](./CONTRIBUTING.md)

## Acknowledgements

We would like to acknowledge the contributions of the following people:

- **Nadeem Bulsara** -  Principal Solutions Architect, Genomics/Multiomics
- **Chris Kaspar** - Principal Solutions Architect
- **Gabriela Karina Paulus** - Solutions Architect
- **Kayla Taylor** - Associate Solutions Architect
- **Eleni Dimokidis** - APJ Healthcare Technical Lead
