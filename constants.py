import os
from aws_cdk import Environment



# Dev Environment
DEV_ENV = Environment( account=os.environ["CDK_DEFAULT_ACCOUNT"], region=os.environ["CDK_DEFAULT_REGION"])
DEV_CONFIG = {
    "AWS_REGION" :  'us-east-1',
    "AWS_BUCKET" :  'omics-eventbridge-solution-dev',
    "JOB_TIMEOUT" : 1500,  # seconds

    # Notification Settings
    # Set to True to send email notifications when workflows complete successfully
    "SEND_COMPLETION_NOTIFICATION": False,
    # SES email configuration (requires verified email addresses in SES)
    # Leave empty to disable SES emails (will use SNS only)
    "SES_SENDER_EMAIL": "",  # e.g., "sender@example.com"
    "SES_RECIPIENT_EMAIL": "",  # e.g., "recipient@example.com"
}


 