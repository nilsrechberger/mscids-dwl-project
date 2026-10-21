# Learner Lab S3 Pilot

This directory documents the AWS Academy Learner Lab pilot setup.

## Current pilot result

The following pipeline was tested successfully:

Open-Meteo / Transport API / GTFS-RT / Municipality
    -> Python loaders
    -> boto3
    -> Amazon S3

The raw data was stored under:

s3://<bucket>/raw/<source>/dt=YYYY-MM-DD/<timestamp>.<extension>

The following sources were tested successfully:

- Weather
- Transport
- GTFS-RT
- Municipality

## Learner Lab limitation

The S3 bucket was initially created with Terraform. The bucket itself was created successfully, but Terraform could not refresh the S3 resource because the Academy environment explicitly denies:

s3:GetBucketObjectLockConfiguration

Therefore, the S3 bucket configuration was completed with the reproducible script:

setup-s3.sh

The script configures:

- S3 public access blocking
- server-side encryption with AES256
- bucket versioning
- resource tags

The Terraform files are retained as documentation of the attempted Infrastructure-as-Code setup. They are not yet the final production configuration.

## Security

The following files must never be committed:

- .env
- API tokens
- terraform.tfvars
- terraform.tfstate
- .terraform/

The production environment should be configured separately. Once the required permissions are available, Terraform should preferably manage S3, IAM, ECR, Lambda and EventBridge.

## Current S3 bucket

The current Learner Lab bucket is:

hslu-dwl-ontime-demo-2026-timo-191554

This bucket belongs to the temporary AWS Academy Learner Lab environment and is not the final production environment.
