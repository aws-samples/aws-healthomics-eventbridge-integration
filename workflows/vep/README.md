# VEP (Variant Effect Predictor) Workflow

## Overview

This workflow runs Ensembl's Variant Effect Predictor (VEP) on AWS HealthOmics. VEP determines the effect of variants (SNPs, insertions, deletions, CNVs, or structural variants) on genes, transcripts, and protein sequences.

## Workflow Parameters

| Parameter | Description | Required | Example |
|-----------|-------------|----------|---------|
| `vcf` | Input VCF file path (S3 URI) | Yes | `s3://bucket/sample.vcf.gz` |
| `vep_cache` | Cache directory path (S3 URI) | Yes | `s3://aws-genomics-static-us-east-1/omics-tutorials/data/databases/vep/` |
| `vep_cache_version` | VEP cache version to use | Yes | `110` |
| `vep_species` | Species name (latin or alias) | Yes | `homo_sapiens` |
| `vep_genome` | Reference genome assembly | Yes | `GRCh38` |
| `ecr_registry` | ECR registry URL for container images | Yes | `<account-id>.dkr.ecr.<region>.amazonaws.com` |
| `id` | Sample identifier | No | `NA12878` |

## Workflow Engine

- **Engine:** Nextflow
- **DSL Version:** 2

## ECR Container Setup (Automated)

AWS HealthOmics private workflows require container images to be stored in Amazon ECR with proper permissions.

### Automated Container Deployment

The CDK stack **automatically handles** the following during `cdk deploy`:

1. **Builds the Docker image** from `workflows/vep/docker/Dockerfile`
2. **Pushes the image to ECR** using CDK's `DockerImageAsset`
3. **Configures ECR repository policy** granting `omics.amazonaws.com` access
4. **Passes the image URI** to the VEP workflow via Lambda environment variables

**No manual Docker push is required.**

### ECR Repository Policy (Auto-configured)

The CDK stack automatically adds this policy to the ECR repository:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "OmicsWorkflowAccess",
            "Effect": "Allow",
            "Principal": {
                "Service": "omics.amazonaws.com"
            },
            "Action": [
                "ecr:GetDownloadUrlForLayer",
                "ecr:BatchGetImage",
                "ecr:BatchCheckLayerAvailability"
            ]
        }
    ]
}
```

Reference: [Amazon ECR Permissions for AWS HealthOmics](https://docs.aws.amazon.com/omics/latest/dev/permissions-ecr.html)

### Container Image Source

The Dockerfile (`workflows/vep/docker/Dockerfile`) uses the official biocontainers image:

```dockerfile
FROM quay.io/biocontainers/ensembl-vep:106.1--pl5321h4a94de4_0
```

### Prerequisites

- **Docker** must be installed and running on the machine where `cdk deploy` is executed
- Docker daemon must have network access to pull from `quay.io`

## Directory Structure

```
vep/
├── docker/
│   └── Dockerfile           # VEP container image (auto-pushed to ECR)
├── nextflow/
│   ├── main.nf              # Main workflow file
│   ├── nextflow.config      # Nextflow configuration
│   ├── conf/
│   │   └── omics.config     # HealthOmics-specific config
│   └── modules/
│       └── ensemblvep/
│           └── main.nf      # VEP module
├── omics/
│   └── workflow-param-desc.json  # Parameter template for HealthOmics
└── test_data/
    ├── sample_manifest_NA12878_2.csv  # Sample manifest for demo
    └── sample_manifest_with_test_data.csv  # Original test manifest
```

## Usage Examples

### Running via AWS HealthOmics

```bash
aws omics start-run \
  --workflow-id <workflow-id> \
  --role-arn <omics-service-role-arn> \
  --output-uri s3://output-bucket/outputs/ \
  --parameters '{
    "vcf": "s3://bucket/sample.vcf.gz",
    "vep_cache": "s3://aws-genomics-static-us-east-1/omics-tutorials/data/databases/vep/",
    "vep_cache_version": "110",
    "vep_species": "homo_sapiens",
    "vep_genome": "GRCh38",
    "vep_container": "123456789012.dkr.ecr.us-east-1.amazonaws.com/cdk-xxx-container-assets-xxx:tag",
    "id": "sample_001"
  }'
```

### Triggered Automatically

This workflow is automatically triggered by EventBridge when the upstream GATK-BP workflow completes successfully. The Lambda function (`post_initial_workflow_lambda`) passes the VCF output from GATK-BP as input to VEP, including the container image URI that was automatically deployed by CDK.

## VEP Cache

The workflow uses pre-cached VEP annotation data stored in S3. AWS provides public VEP cache files in region-specific buckets:

```
s3://aws-genomics-static-{region}/omics-tutorials/data/databases/vep/
```

Supported cache versions and genomes:
- **Version:** 110
- **Genome:** GRCh38
- **Species:** homo_sapiens

## Output

The workflow produces annotated VCF files with variant effect predictions including:
- Gene and transcript annotations
- Protein position and amino acid changes
- SIFT and PolyPhen predictions
- Regulatory feature annotations
- Known variant identifiers (dbSNP, COSMIC, etc.)

## Test Data

Sample manifests are provided in the `test_data/` directory for testing the complete pipeline:

1. **sample_manifest_NA12878.csv** - NA12878 Sample_U0a read group
2. **sample_manifest_NA12878_2.csv** - NA12878 Sample_U0b read group

To run a demo:
```bash
# Replace {aws-region} with your actual region (e.g., us-east-1)
# Upload manifest to trigger the pipeline
aws s3 cp sample_manifest_NA12878.csv s3://INPUT_BUCKET/fastqs/
```

## References

- [Ensembl VEP Documentation](https://www.ensembl.org/info/docs/tools/vep/index.html)
- [AWS HealthOmics Documentation](https://docs.aws.amazon.com/omics/)
- [nf-core/ensemblvep](https://nf-co.re/modules/ensemblvep)
