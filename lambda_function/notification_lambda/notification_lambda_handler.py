import boto3
import os
import logging
from botocore.exceptions import ClientError

# Environment variables
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']
VEP_WORKFLOW_ID = os.environ['VEP_WORKFLOW_ID']
GATK_WORKFLOW_ID = os.environ['GATK_WORKFLOW_ID']
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
# Completion notification flag (set to 'True' to enable notifications for COMPLETED runs)
SEND_COMPLETION_NOTIFICATION = os.environ.get('SEND_COMPLETION_NOTIFICATION', 'False').lower() == 'true'
# SES configuration (optional - falls back to SNS if not configured)
SES_SENDER_EMAIL = os.environ.get('SES_SENDER_EMAIL', '')
SES_RECIPIENT_EMAIL = os.environ.get('SES_RECIPIENT_EMAIL', '')

# AWS clients
omics = boto3.client('omics')
s3 = boto3.client('s3')
sns = boto3.client('sns')
ses = boto3.client('ses')

# Configure logging
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)


def parse_s3_uri(s3_uri):
    """Parse S3 URI into bucket and prefix."""
    path_parts = s3_uri.replace("s3://", "").split("/")
    bucket = path_parts.pop(0)
    prefix = "/".join(path_parts)
    return bucket, prefix


def generate_presigned_urls(bucket, prefix, target_extensions, expires_in=86400):
    """Generate presigned URLs for files matching target extensions.

    Args:
        bucket: S3 bucket name
        prefix: S3 prefix to search
        target_extensions: List of file extensions to match
        expires_in: URL validity in seconds (default: 1 day)

    Returns:
        List of dictionaries with filename and presigned URL
    """
    presigned_urls = []

    try:
        paginator = s3.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

        for page in page_iterator:
            for obj in page.get('Contents', []):
                key = obj['Key']
                if any(key.endswith(ext) for ext in target_extensions):
                    try:
                        url = s3.generate_presigned_url(
                            'get_object',
                            Params={'Bucket': bucket, 'Key': key},
                            ExpiresIn=expires_in
                        )
                        filename = key.split('/')[-1]
                        file_size = obj.get('Size', 0)
                        presigned_urls.append({
                            'filename': filename,
                            'url': url,
                            'size': file_size
                        })
                        logger.info(f"Generated presigned URL for: {filename}")
                    except ClientError as e:
                        logger.error(f"Failed to generate presigned URL for {key}: {e}")
    except ClientError as e:
        logger.error(f"Failed to list objects in s3://{bucket}/{prefix}: {e}")

    return presigned_urls


def format_file_size(size_bytes):
    """Format file size in human readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def get_file_description(filename):
    """Get description based on file extension."""
    if filename.endswith('.summary.html'):
        return "VEP Summary Report"
    elif filename.endswith('.ann.vcf.gz'):
        return "Annotated VCF"
    elif filename.endswith('.ann.json.gz'):
        return "JSON Annotation"
    elif filename.endswith('.ann.tab.gz'):
        return "Tab Annotation"
    else:
        return "Output File"


def format_notification_text(workflow_type, run_name, run_id, output_uri, presigned_urls=None):
    """Format plain text notification message for SNS.

    Args:
        workflow_type: Type of workflow (GATK-BP or VEP)
        run_name: Name of the run
        run_id: HealthOmics run ID
        output_uri: S3 output location
        presigned_urls: Optional list of presigned URLs for VEP results

    Returns:
        Formatted plain text message string
    """
    separator = "=" * 50

    message_parts = [
        separator,
        "AWS HealthOmics Workflow Completed",
        separator,
        "",
        f"Workflow: {workflow_type}",
        f"Run Name: {run_name}",
        f"Run ID: {run_id}",
        f"Status: COMPLETED",
        ""
    ]

    # Add presigned URLs section for VEP workflow
    if presigned_urls:
        message_parts.extend([
            "Results (Presigned URLs - Valid for 1 day):",
            ""
        ])
        for idx, file_info in enumerate(presigned_urls, 1):
            filename = file_info['filename']
            url = file_info['url']
            size = format_file_size(file_info.get('size', 0))
            description = get_file_description(filename)

            message_parts.extend([
                f"{idx}. {filename}",
                f"   Type: {description} | Size: {size}",
                f"   Download: <{url}>",
                ""
            ])

    # Add output location
    message_parts.extend([
        f"Output Location:",
        f"{output_uri}/{run_id}/",
        ""
    ])

    # Add note for GATK workflow
    if workflow_type == "GATK-BP Germline fq2vcf":
        message_parts.extend([
            "Note: VEP annotation workflow will start automatically.",
            ""
        ])

    message_parts.append(separator)

    return "\n".join(message_parts)


def format_notification_html(workflow_type, run_name, run_id, output_uri, presigned_urls=None):
    """Format HTML notification message for SES email.

    Args:
        workflow_type: Type of workflow (GATK-BP or VEP)
        run_name: Name of the run
        run_id: HealthOmics run ID
        output_uri: S3 output location
        presigned_urls: Optional list of presigned URLs for VEP results

    Returns:
        Formatted HTML message string
    """
    # Build download links HTML
    download_section = ""
    if presigned_urls:
        download_items = []
        for file_info in presigned_urls:
            filename = file_info['filename']
            url = file_info['url']
            size = format_file_size(file_info.get('size', 0))
            description = get_file_description(filename)

            # Color-code based on file type
            if 'summary.html' in filename:
                icon = "📊"
                color = "#2e7d32"  # Green for reports
            elif '.vcf' in filename:
                icon = "🧬"
                color = "#1565c0"  # Blue for VCF
            else:
                icon = "📄"
                color = "#6a1b9a"  # Purple for other

            download_items.append(f'''
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #e0e0e0;">
                    <span style="font-size: 20px;">{icon}</span>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #e0e0e0;">
                    <strong style="color: {color};">{filename}</strong><br>
                    <span style="color: #666; font-size: 13px;">{description} • {size}</span>
                </td>
                <td style="padding: 12px; border-bottom: 1px solid #e0e0e0; text-align: right;">
                    <a href="{url}"
                       style="display: inline-block; padding: 8px 16px; background-color: {color};
                              color: white; text-decoration: none; border-radius: 4px; font-weight: bold;">
                        Download
                    </a>
                </td>
            </tr>
            ''')

        download_section = f'''
        <div style="margin: 20px 0;">
            <h3 style="color: #333; border-bottom: 2px solid #1976d2; padding-bottom: 8px;">
                📥 Download Results
            </h3>
            <p style="color: #666; font-size: 13px; margin-bottom: 15px;">
                ⏰ Links valid for <strong>24 hours</strong>
            </p>
            <table style="width: 100%; border-collapse: collapse; background: #fafafa; border-radius: 8px;">
                {"".join(download_items)}
            </table>
        </div>
        '''

    # Add note for GATK workflow
    note_section = ""
    if workflow_type == "GATK-BP Germline fq2vcf":
        note_section = '''
        <div style="background: #e3f2fd; padding: 12px; border-radius: 4px; margin: 15px 0; border-left: 4px solid #1976d2;">
            <strong>ℹ️ Next Step:</strong> VEP annotation workflow will start automatically.
        </div>
        '''

    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                 max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;">
        <div style="background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden;">
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #1976d2 0%, #1565c0 100%); padding: 25px; text-align: center;">
                <h1 style="color: white; margin: 0; font-size: 22px;">
                    ✅ Workflow Completed
                </h1>
                <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0; font-size: 14px;">
                    AWS HealthOmics
                </p>
            </div>

            <!-- Content -->
            <div style="padding: 25px;">
                <!-- Workflow Info -->
                <table style="width: 100%; margin-bottom: 20px;">
                    <tr>
                        <td style="padding: 8px 0; color: #666; width: 120px;">Workflow:</td>
                        <td style="padding: 8px 0; font-weight: bold; color: #333;">{workflow_type}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; color: #666;">Run Name:</td>
                        <td style="padding: 8px 0; color: #333;">{run_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; color: #666;">Run ID:</td>
                        <td style="padding: 8px 0; color: #333; font-family: monospace;">{run_id}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; color: #666;">Status:</td>
                        <td style="padding: 8px 0;">
                            <span style="background: #4caf50; color: white; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: bold;">
                                COMPLETED
                            </span>
                        </td>
                    </tr>
                </table>

                {note_section}

                {download_section}

                <!-- Output Location -->
                <div style="background: #f5f5f5; padding: 12px; border-radius: 4px; margin-top: 20px;">
                    <strong style="color: #666; font-size: 12px;">📁 OUTPUT LOCATION</strong><br>
                    <code style="color: #1976d2; font-size: 13px; word-break: break-all;">
                        {output_uri}/{run_id}/
                    </code>
                </div>
            </div>

            <!-- Footer -->
            <div style="background: #fafafa; padding: 15px; text-align: center; border-top: 1px solid #e0e0e0;">
                <p style="margin: 0; color: #999; font-size: 12px;">
                    Sent by AWS HealthOmics EventBridge Integration
                </p>
            </div>
        </div>
    </body>
    </html>
    '''

    return html


def handler(event, context):
    """Lambda handler for workflow completion notifications.

    Triggered by EventBridge when a HealthOmics workflow completes.
    Sends SNS notification with optional presigned URLs for VEP results.
    """
    logger.info(f"Received event: {event}")

    try:
        # Extract run information from EventBridge event
        run_arn = event['detail']['arn']
        run_id = run_arn.split('/')[-1]
        status = event['detail']['status']

        # Verify this is a COMPLETED event
        if status != 'COMPLETED':
            logger.info(f"Ignoring non-COMPLETED status: {status}")
            return {
                'statusCode': 200,
                'message': f'Ignored event with status: {status}'
            }

        # Check if completion notifications are enabled
        if not SEND_COMPLETION_NOTIFICATION:
            logger.info("Completion notifications disabled (SEND_COMPLETION_NOTIFICATION=False)")
            return {
                'statusCode': 200,
                'message': 'Completion notifications disabled'
            }

        # Get run details from HealthOmics
        logger.info(f"Getting run details for run ID: {run_id}")
        run_info = omics.get_run(id=run_id)

        workflow_id = run_info.get('workflowId', '')
        run_name = run_info.get('name', run_id)
        output_uri = run_info.get('outputUri', '')

        logger.info(f"Workflow ID: {workflow_id}, Run Name: {run_name}")

        # Determine workflow type and generate presigned URLs if VEP
        is_vep = (str(workflow_id) == str(VEP_WORKFLOW_ID))
        is_gatk = (str(workflow_id) == str(GATK_WORKFLOW_ID))

        if is_vep:
            workflow_type = "VEP (Variant Effect Predictor)"
            logger.info("Processing VEP workflow completion")

            # Generate presigned URLs for VEP output files
            run_output_path = f"{output_uri}/{run_id}"
            bucket, prefix = parse_s3_uri(run_output_path)

            target_extensions = [
                '.summary.html',
                '.ann.vcf.gz',
                '.ann.json.gz',
                '.ann.tab.gz'
            ]

            presigned_urls = generate_presigned_urls(
                bucket, prefix, target_extensions, expires_in=86400  # 1 day
            )
            logger.info(f"Generated {len(presigned_urls)} presigned URLs")

        elif is_gatk:
            workflow_type = "GATK-BP Germline fq2vcf"
            presigned_urls = None
            logger.info("Processing GATK workflow completion")
        else:
            # Unknown workflow - still send notification but without special handling
            workflow_type = f"Unknown Workflow (ID: {workflow_id})"
            presigned_urls = None
            logger.info(f"Processing unknown workflow: {workflow_id}")

        # Prepare subject
        subject = f"[HealthOmics] {workflow_type} Completed - {run_name}"
        if len(subject) > 100:
            subject = subject[:97] + "..."

        response_data = {
            'statusCode': 200,
            'workflowType': workflow_type,
            'runId': run_id
        }

        # Send HTML email via SES if configured
        if SES_SENDER_EMAIL and SES_RECIPIENT_EMAIL:
            try:
                html_message = format_notification_html(
                    workflow_type=workflow_type,
                    run_name=run_name,
                    run_id=run_id,
                    output_uri=output_uri,
                    presigned_urls=presigned_urls
                )

                # Also create plain text version for email clients that don't support HTML
                text_message = format_notification_text(
                    workflow_type=workflow_type,
                    run_name=run_name,
                    run_id=run_id,
                    output_uri=output_uri,
                    presigned_urls=presigned_urls
                )

                logger.info(f"Sending HTML email via SES to: {SES_RECIPIENT_EMAIL}")
                ses_response = ses.send_email(
                    Source=SES_SENDER_EMAIL,
                    Destination={
                        'ToAddresses': [SES_RECIPIENT_EMAIL]
                    },
                    Message={
                        'Subject': {
                            'Data': subject,
                            'Charset': 'UTF-8'
                        },
                        'Body': {
                            'Text': {
                                'Data': text_message,
                                'Charset': 'UTF-8'
                            },
                            'Html': {
                                'Data': html_message,
                                'Charset': 'UTF-8'
                            }
                        }
                    }
                )
                logger.info(f"SES send_email response: {ses_response}")
                response_data['sesMessageId'] = ses_response.get('MessageId')
                response_data['message'] = 'HTML email sent successfully via SES'

            except ClientError as e:
                logger.error(f"SES send_email failed: {e}")
                # Fall back to SNS if SES fails
                logger.info("Falling back to SNS notification")

        # Always send to SNS topic as well (for other subscribers like Lambda)
        text_message = format_notification_text(
            workflow_type=workflow_type,
            run_name=run_name,
            run_id=run_id,
            output_uri=output_uri,
            presigned_urls=presigned_urls
        )

        logger.info(f"Publishing to SNS topic: {SNS_TOPIC_ARN}")
        sns_response = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=text_message
        )

        logger.info(f"SNS publish response: {sns_response}")
        response_data['snsMessageId'] = sns_response.get('MessageId')
        if 'message' not in response_data:
            response_data['message'] = 'Notification sent successfully via SNS'

        return response_data

    except ClientError as e:
        logger.error(f"AWS client error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise
