# AWS Data Lake IaC

This directory contains the first, backend-less Terraform layer for the project. It is intentionally safe to validate locally without AWS credentials and does not deploy anything by itself.

## Planned physical resources

- one S3 data-lake bucket for `raw/`, `reference/`, `silver/` and `gold/` prefixes;
- one separately bootstrapped S3 state bucket, managed by this configuration only after the backend bootstrap decision is complete;
- one least-privilege managed policy for the loader's S3 access.
- an ECR repository, Lambda container execution role and CloudWatch log group;
- an optional Lambda container function and Step Functions batch loop when `lambda_image_uri` is configured.

The state bucket is disabled by default with `create_state_bucket = false`. A Terraform backend cannot safely create the bucket that stores its own state in the same first apply. Bootstrap and remote-backend activation are therefore a later, explicit step.

## Local validation

From the repository root:

```bash
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
terraform -chdir=infra plan -var-file=environments/test.tfvars.example
```

The example variables contain no credentials and the placeholder bucket name must not be applied.

## Data-lake key contract

Run-based objects use the application contract:

```text
raw/<source>/dt=<observation_date>/run=<run_id>/part0000.json
raw/<source>/dt=<observation_date>/run=<run_id>/manifest_part0000.json
raw/<source>/dt=<observation_date>/run=<run_id>/manifest.json
```

The runtime deployment sequence and state-machine input contract are documented in [`runtime.md`](runtime.md). EventBridge scheduling is intentionally deferred until the manual state-machine path is verified.
