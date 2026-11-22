# AWS Data Lake IaC

Terraform for the AWS data lake and its runtime. Each environment (`test`, `prod`) is a separate stack: all resource names contain `var.environment`, and the S3 backend is configured per environment at `terraform init` (partial backend configuration in `backend.tf`).

## Resources

- S3 data-lake bucket with `raw/`, `reference/`, `silver/` and `gold/` prefixes (versioning, encryption, public-access block, lifecycle rules);
- optional Terraform state bucket (`create_state_bucket`, normally bootstrapped separately);
- least-privilege S3 policy for the loader;
- ECR repository (immutable tags, scan on push), Lambda execution role and CloudWatch log group;
- when `lambda_image_uri` is set: the Lambda container function and the Step Functions workflows `loader` (batched sources) `istdaten-sync` (Ist-Daten v2 CKAN sync) and `istdaten-archive` (one-off historical import from the monthly ZIP archives, started manually);
- daily EventBridge rules (`eventbridge_schedule_enabled`, disabled by default);
- SNS alarm topic, CloudWatch alarms and a monthly budget (`alarm_emails`, `monthly_budget_usd`).

Secrets are never Terraform values: the CKAN API key is created manually in Secrets Manager and passed by ARN (`ckan_api_key_secret_arn`). Details and the deployment sequence: [`runtime.md`](runtime.md).

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
raw/istdaten_v2/dt=<operating_day>/run=istdaten-v2-<day>-<hash12>/data.csv
raw/istdaten_v2/dt=<operating_day>/run=istdaten-v2-<day>-<hash12>/manifest.json
```

`dt` is always the observation or operating day, never the ingestion date. The state-machine input contracts are documented in [`runtime.md`](runtime.md).
