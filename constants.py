import os
from aws_cdk import Environment



# Dev Environment
DEV_ENV = Environment( account=os.environ["CDK_DEFAULT_ACCOUNT"], region=os.environ["CDK_DEFAULT_REGION"])
DEV_CONFIG = { 
    
 
    "AWS_REGION" :  'us-east-1',
    "AWS_BUCKET" :  'omics-eventbridge-solution-dev',
    "JOB_TIMEOUT" : 1500 , #seconds
    
    # SQS QUEUE INFORMATION:
    "SQS_MESSAGE_VISIBILITY" :  1200,           # Timeout (secs) for messages in flight (average time to be processed)


    # PLUGINS
    "REQUIREMENTS_FILE" :  '/files/requirements.txt',       # Path to requirements file

}


 