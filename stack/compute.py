from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_omics as omics,
    aws_lambda_event_sources as lambda_event_sources,
    aws_events as events,
    aws_events_targets as events_targets,
    aws_sns as sns,
    aws_iam as iam,
    aws_s3_assets as s3_assets,
    aws_ecr as ecr,
    aws_ecr_assets as ecr_assets,
    aws_codebuild as codebuild,
    custom_resources as cr,
    Aspects
)

from constructs import Construct
import os
import json
import cdk_nag 
 

###########################################################################################################
#                                       Workflow
###########################################################################################################


class omics_workflow_Stack(Stack):

    def __init__(self, scope: Construct, construct_id: str, config, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        aws_account = os.environ["CDK_DEFAULT_ACCOUNT"]
        aws_region = os.environ["CDK_DEFAULT_REGION"]

        # Prefix for all resource names
        APP_NAME = f"healthomics"
 
        # currently set to run HealthOmics Ready2Run workflow
        # GATK-BP Germline fq2vcf for 30x genome
        READY2RUN_WORKFLOW_ID = "9500764"

        ################################################################################################
        #################################### Buckets ##############################################
        
        # Create Input S3 bucket
        bucket_input = s3.Bucket(self,
                                 f"{APP_NAME}-cka-input-{aws_account}-{aws_region}",
                                 enforce_ssl=True)

        # Create Results S3 bucket
        bucket_output = s3.Bucket(self,
                                  f"{APP_NAME}-cka-output-{aws_account}-{aws_region}",
                                  enforce_ssl=True)


        ################################################################################################
        #################################### Notification ##############################################
        
        # SNS Topic for failure notifications
        sns_topic = sns.Topic(self, f'{APP_NAME}_workflow_status_topic',
            display_name=f"{APP_NAME}_workflow_status_topic",
            topic_name=f"{APP_NAME}_workflow_status_topic"
        )

        # Add an email subscription to the SNS topic (subscribe manually or replace below)
        #sns_topic.add_subscription(subs.EmailSubscription(""))
        
        # Create an EventBridge rule that sends SNS notification on failure
        rule_workflow_status_topic = events.Rule(
            self, f"{APP_NAME}_rule_workflow_status_topic",
            event_pattern=events.EventPattern(
                source=["aws.omics"],
                detail_type=["Run Status Change"],
                detail={
                    "status": [
                        "FAILED"
                    ]
                }
            )
        )
        rule_workflow_status_topic.add_target(events_targets.SnsTopic(sns_topic))
        
        
        # Grant EventBridge permission to publish to the SNS topic
        sns_topic.grant_publish(iam.ServicePrincipal('events.amazonaws.com'))        
        

        
        ################################################################################################
        #################################### Identity and access management ############################
 

        # Create an IAM service role for HealthOmics workflows ########################################
        omics_role = iam.Role(self, f"{APP_NAME}-omics-service-role",
            assumed_by=iam.ServicePrincipal("omics.amazonaws.com"),
        )
        
        # Limit to buckets from where inputs need to be read
        omics_s3_read_policy = iam.PolicyStatement(
            actions = [
                's3:ListBucket',
                's3:GetObject',
            ],
            resources = [
                bucket_input.bucket_arn,
                    bucket_output.bucket_arn,
                    bucket_input.bucket_arn + "/*",
                    bucket_output.bucket_arn + "/*"
            ]
        )
        omics_role.add_to_policy(omics_s3_read_policy)

        # Limit to buckets where outputs need to be written
        omics_s3_write_policy = iam.PolicyStatement(
            actions = [
                's3:ListBucket',
                's3:PutObject',
            ],
            resources = [
                    bucket_output.bucket_arn,
                    bucket_output.bucket_arn + "/*"
            ]
        )
        omics_role.add_to_policy(omics_s3_write_policy)

        # ECR image access
        omics_ecr_policy = iam.PolicyStatement(
            actions = [
                'ecr:BatchGetImage',
                'ecr:GetDownloadUrlForLayer',
                'ecr:BatchCheckLayerAvailability'
            ],
            resources=[f'arn:aws:ecr:{aws_region}:{aws_account}:repository/*']
        )
        omics_role.add_to_policy(omics_ecr_policy)

        # CloudWatch logging access
        omics_logging_policy = iam.PolicyStatement(
            actions = [
                'logs:CreateLogGroup',
                'logs:DescribeLogStreams',
                'logs:CreateLogStream',
                'logs:PutLogEvents'
            ],
            resources = [
                f'arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/omics/WorkflowLog:log-stream:*',
                f'arn:aws:logs:{aws_region}:{aws_account}:log-group:/aws/omics/WorkflowLog:*'
            ]
        )
        omics_role.add_to_policy(omics_logging_policy)
    
        omics_kms_policy = iam.PolicyStatement(
            actions = [ 
                'kms:Decrypt', 
                'kms:GenerateDataKey'
                ],
            resources = ['*']
        )
        omics_role.add_to_policy(omics_kms_policy)

        # Allow Omics service role to access some
        # common public AWS S3 buckets with test data
        omics_role_additional_policy = iam.PolicyStatement(
            actions = [
                            "s3:Get*",
                            "s3:List*"
                        ],
            resources = [
                "arn:aws:s3:::broad-references",
                "arn:aws:s3:::broad-references/*",
                "arn:aws:s3:::giab",
                "arn:aws:s3:::giab/*",
                f"arn:aws:s3:::aws-genomics-static-{aws_region}",
                f"arn:aws:s3:::aws-genomics-static-{aws_region}/*",
                f"arn:aws:s3:::omics-{aws_region}",
                f"arn:aws:s3:::omics-{aws_region}/*"     
                ]
            )
        omics_role.add_to_policy(omics_role_additional_policy)

        # Create an IAM role for the Lambda functions
        lambda_role = iam.Role(self, f"{APP_NAME}-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        # allow the Lambda functions to pass Omics service
        # role to the Omics service
        lambda_iam_passrole_policy = iam.PolicyStatement(
            actions = [
                'iam:PassRole'
                ],
                resources=[
                    omics_role.role_arn
                ]
        )
        lambda_role.add_to_policy(lambda_iam_passrole_policy)

        lambda_s3_policy = iam.PolicyStatement(
            actions = [
                's3:ListBucket',
                's3:GetObject',
                's3:PutObject'
                ],
                resources=[
                    bucket_input.bucket_arn,
                    bucket_output.bucket_arn,
                    bucket_input.bucket_arn + "/*",
                    bucket_output.bucket_arn + "/*"
                ]
        )
        lambda_role.add_to_policy(lambda_s3_policy)

        lambda_omics_policy = iam.PolicyStatement(
            actions = [
                'omics:StartRun',
                'omics:TagResource',
                'omics:GetRun'
            ],
            resources = ['*']
        )
        lambda_role.add_to_policy(lambda_omics_policy)

        # KMS permission for SNS topic encryption
        lambda_kms_policy = iam.PolicyStatement(
            actions = [
                'kms:GenerateDataKey',
                'kms:Decrypt'
            ],
            resources = ['*']
        )
        lambda_role.add_to_policy(lambda_kms_policy)

        # SES permission for sending HTML emails
        lambda_ses_policy = iam.PolicyStatement(
            actions = [
                'ses:SendEmail',
                'ses:SendRawEmail'
            ],
            resources = ['*']
        )
        lambda_role.add_to_policy(lambda_ses_policy)

        ################################################################################################
        #################################### ECR Docker Image for VEP ##################################

        # Create a dedicated ECR repository for VEP (not using CDK bootstrap repo)
        # This allows proper resource policy configuration for HealthOmics
        vep_ecr_repo = ecr.Repository(self, f"{APP_NAME}-vep-repo",
            repository_name=f"{APP_NAME}-vep",
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            image_scan_on_push=True
        )

        # Add resource policy allowing HealthOmics service to pull images
        # Reference: https://docs.aws.amazon.com/omics/latest/dev/permissions-ecr.html
        vep_ecr_repo.add_to_resource_policy(
            iam.PolicyStatement(
                sid="OmicsWorkflowAccess",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("omics.amazonaws.com")],
                actions=[
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchGetImage",
                    "ecr:BatchCheckLayerAvailability"
                ],
                conditions={
                    "StringEquals": {
                        "aws:SourceAccount": aws_account
                    }
                }
            )
        )

        # CodeBuild project to build and push VEP Docker image to dedicated ECR repo
        vep_build_project = codebuild.Project(self, f"{APP_NAME}-vep-build",
            project_name=f"{APP_NAME}-vep-image-build",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True  # Required for Docker builds
            ),
            environment_variables={
                "ECR_REPO_URI": codebuild.BuildEnvironmentVariable(value=vep_ecr_repo.repository_uri),
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(value=aws_account),
                "AWS_REGION": codebuild.BuildEnvironmentVariable(value=aws_region)
            },
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "pre_build": {
                        "commands": [
                            "echo Logging in to Amazon ECR...",
                            "aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"
                        ]
                    },
                    "build": {
                        "commands": [
                            "echo Building VEP Docker image...",
                            "docker pull quay.io/biocontainers/ensembl-vep:106.1--pl5321h4a94de4_0",
                            "docker tag quay.io/biocontainers/ensembl-vep:106.1--pl5321h4a94de4_0 $ECR_REPO_URI:latest",
                            "docker tag quay.io/biocontainers/ensembl-vep:106.1--pl5321h4a94de4_0 $ECR_REPO_URI:106.1"
                        ]
                    },
                    "post_build": {
                        "commands": [
                            "echo Pushing VEP image to ECR...",
                            "docker push $ECR_REPO_URI:latest",
                            "docker push $ECR_REPO_URI:106.1",
                            "echo Build completed successfully"
                        ]
                    }
                }
            }),
            timeout=Duration.minutes(30)
        )

        # Grant CodeBuild permission to push to ECR
        vep_ecr_repo.grant_pull_push(vep_build_project)

        # Custom Resource to trigger CodeBuild during deployment
        trigger_build = cr.AwsCustomResource(self, f"{APP_NAME}-trigger-vep-build",
            on_create=cr.AwsSdkCall(
                service="CodeBuild",
                action="startBuild",
                parameters={
                    "projectName": vep_build_project.project_name
                },
                physical_resource_id=cr.PhysicalResourceId.of(f"{APP_NAME}-vep-build-trigger")
            ),
            on_update=cr.AwsSdkCall(
                service="CodeBuild",
                action="startBuild",
                parameters={
                    "projectName": vep_build_project.project_name
                },
                physical_resource_id=cr.PhysicalResourceId.of(f"{APP_NAME}-vep-build-trigger")
            ),
            policy=cr.AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    actions=["codebuild:StartBuild"],
                    resources=[vep_build_project.project_arn]
                )
            ])
        )

        # Ensure build is triggered after ECR repo is created
        trigger_build.node.add_dependency(vep_ecr_repo)
        trigger_build.node.add_dependency(vep_build_project)

        # Store the full image URI for use in Lambda environment variables
        vep_container_image_uri = f"{vep_ecr_repo.repository_uri}:latest"

        ################################################################################################
        #################################### Create HealthOmics Workflow ###############################

        PRIVATE_WORKFLOW_NAME = 'vep'
        workflow_description = "Workflow to run Variant Effect Predictor (VEP)"

        # Define the asset
        private_workflow_dir = f"workflows/{PRIVATE_WORKFLOW_NAME}/"
        workflow_zip_asset = s3_assets.Asset(self, PRIVATE_WORKFLOW_NAME, 
                                             path=private_workflow_dir + 'nextflow/') 
        
        # load parameters
        with open(private_workflow_dir + "omics/workflow-param-desc.json") as pm:
            parameters = json.load(pm)
        

        private_workflow_cfn = omics.CfnWorkflow(self, f"{APP_NAME}-workflow-{PRIVATE_WORKFLOW_NAME}",
            name=PRIVATE_WORKFLOW_NAME,
            description=workflow_description,        
            engine="NEXTFLOW",
            definition_uri= f"s3://{workflow_zip_asset.s3_bucket_name}/{workflow_zip_asset.s3_object_key}",            
            main="main.nf",            
            parameter_template=parameters,
            storage_capacity=1200,
            tags={
            }
        )

 
        
        ################################################################################################
        #################################### Lambda Initial ############################################

        # Create Lambda function to submit 
        # initial HealthOmics workflow
        initial_workflow_lambda = lambda_.Function(
            self, f"{APP_NAME}_initial_workflow_lambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="initial_workflow_lambda_handler.handler",
            code=lambda_.Code.from_asset("lambda_function/initial_workflow_lambda"),
            role=lambda_role,
            timeout=Duration.seconds(60),
            retry_attempts=1,
            environment={
                "OMICS_ROLE": omics_role.role_arn,
                "OUTPUT_S3_LOCATION": "s3://" + bucket_output.bucket_name + "/outputs",
                "WORKFLOW_ID" : READY2RUN_WORKFLOW_ID,
                "ECR_REGISTRY": aws_account + ".dkr.ecr." + aws_region + ".amazonaws.com",
                "LOG_LEVEL": "INFO"
            }                  
        )

        # Add S3 event source to Lambda
        # should trigger if a .csv is 
        # dropped in a specified prefix
        initial_workflow_lambda.add_event_source(
            lambda_event_sources.S3EventSource(
            bucket_input, 
            events=[s3.EventType.OBJECT_CREATED],
            filters=[s3.NotificationKeyFilter(prefix="fastqs/", suffix=".csv")]
        ))

        ################################################################################################
        #################################### Lambda Post Initial #######################################

        
        # Create Lambda function to submit second Omics pipeline
        second_workflow_lambda = lambda_.Function(
            self, f"{APP_NAME}_post_initial_workflow_lambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="post_initial_workflow_lambda_handler.handler",
            code=lambda_.Code.from_asset("lambda_function/post_initial_workflow_lambda"),
            role=lambda_role,
            timeout=Duration.seconds(60),
            retry_attempts=1,
            environment={
                "OMICS_ROLE": omics_role.role_arn,
                "OUTPUT_S3_LOCATION": "s3://" + bucket_output.bucket_name + "/outputs",
                "WORKFLOW_ID": private_workflow_cfn.attr_id,
                "UPSTREAM_WORKFLOW_ID": READY2RUN_WORKFLOW_ID,
                "VEP_CONTAINER_IMAGE": vep_container_image_uri,
                "SPECIES": "homo_sapiens",
                "DIR_CACHE": f"s3://aws-genomics-static-{aws_region}/omics-tutorials/data/databases/vep/",
                "CACHE_VERSION": "110",
                "GENOME": "GRCh38",
                "LOG_LEVEL": "INFO"
            }            
        )


        ################################################################################################
        #################################### Event Bridge Rule for post initial Lambda  ################


        # Create an EventBridge rule that triggers lambda2
        rule_second_workflow_lambda = events.Rule(
            self, f"{APP_NAME}_rule_second_workflow_lambda",
            event_pattern=events.EventPattern(
                source=["aws.omics"],
                detail_type=["Run Status Change"],                
                detail={
                    "status": [
                        "COMPLETED"
                    ]
                }
            )
        )
        rule_second_workflow_lambda.add_target(events_targets.LambdaFunction(second_workflow_lambda))

        ################################################################################################
        #################################### Notification Lambda for Completion ########################

        # Get notification settings from config
        send_completion_notification = config.get("SEND_COMPLETION_NOTIFICATION", False)
        ses_sender_email = config.get("SES_SENDER_EMAIL", "")
        ses_recipient_email = config.get("SES_RECIPIENT_EMAIL", "")

        # Create Lambda function for workflow completion notifications
        # Sends HTML emails via SES with clickable presigned URLs
        notification_lambda = lambda_.Function(
            self, f"{APP_NAME}_notification_lambda",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="notification_lambda_handler.handler",
            code=lambda_.Code.from_asset("lambda_function/notification_lambda"),
            role=lambda_role,
            timeout=Duration.seconds(60),
            retry_attempts=1,
            environment={
                "SNS_TOPIC_ARN": sns_topic.topic_arn,
                "VEP_WORKFLOW_ID": private_workflow_cfn.attr_id,
                "GATK_WORKFLOW_ID": READY2RUN_WORKFLOW_ID,
                "SES_SENDER_EMAIL": ses_sender_email,
                "SES_RECIPIENT_EMAIL": ses_recipient_email,
                "SEND_COMPLETION_NOTIFICATION": str(send_completion_notification),
                "LOG_LEVEL": "INFO"
            }
        )

        # Grant notification lambda permission to publish to SNS
        sns_topic.grant_publish(notification_lambda)

        # The notification lambda uses the same EventBridge rule as second_workflow_lambda
        # since both need to respond to COMPLETED events
        rule_second_workflow_lambda.add_target(events_targets.LambdaFunction(notification_lambda))

        #Aspects.of(self).add(cdk_nag.AwsSolutionsChecks())
 