#!/usr/bin/env bash
set -euo pipefail

BUCKET_NAME="${1:?Usage: ./setup-s3.sh <bucket-name>}"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "Configuring bucket: ${BUCKET_NAME}"
echo "Region: ${REGION}"

aws s3api head-bucket \
  --bucket "$BUCKET_NAME" \
  --region "$REGION"

aws s3api put-public-access-block \
  --bucket "$BUCKET_NAME" \
  --region "$REGION" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-encryption \
  --bucket "$BUCKET_NAME" \
  --region "$REGION" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-bucket-versioning \
  --bucket "$BUCKET_NAME" \
  --region "$REGION" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-tagging \
  --bucket "$BUCKET_NAME" \
  --region "$REGION" \
  --tagging 'TagSet=[{Key=Project,Value=OnTimeInEveryMunicipality},{Key=Environment,Value=demo},{Key=ManagedBy,Value=AWS-CLI-Script}]'

echo "S3 bucket configuration completed successfully."
