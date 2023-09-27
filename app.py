#!/usr/bin/env python3
import aws_cdk as cdk
from stack.compute import omics_workflow_Stack
import constants

app = cdk.App()

omics_workflow  = omics_workflow_Stack(app, "omics-eventbridge-solution",  env=constants.DEV_ENV,      config=constants.DEV_CONFIG  )

app.synth()
