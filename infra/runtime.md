# AWS Runtime Orchestration

The deployable runtime layer on top of the S3 data lake.

## Architecture

```text
ECR (immutable image)
        |
        v
Lambda container (src.run.handler)
        |  S3 read reference/ and raw/municipality
        |  S3 write raw/ and deterministic manifests
        v
Step Functions Standard workflows
  loader:        InvokeBatch -> HasNextBatch -> PrepareNextBatch (loop)
                                         \-> FinalizeManifest -> Succeeded
  istdaten-sync: PlanSync -> LoadDays (Map, one Lambda per day) -> CheckFreshness
        ^
EventBridge (daily, disabled by default)

CloudWatch alarms -> SNS topic -> e-mail      AWS Budget -> e-mail
```

The execution role is intentionally limited to CloudWatch logging and the existing loader S3 policy. The S3 policy reads the municipality/weather reference area and the municipality input, lists the relevant prefixes, and writes raw objects. API tokens must not be stored in Terraform variables or Lambda environment variables; use Secrets Manager/SSM and add the retrieval contract in a separate change.

The `municipality_weather` loader accepts both local paths and an immutable `s3://bucket/key` CSV URI. Configure `municipality_weather_points_uri` with the versioned object under `reference/`. The `point_snapshot` field in the run event is retained in the final manifest for lineage and is validated as part of the run contract.


The Lambda also requires this non-secret public endpoint in `lambda_environment`:

```hcl
MUNICIPALITY_XLSX = "https://www.agvchapp.bfs.admin.ch/de/state/results/xls?SnapshotDate=01.01.2026"
```

The Ist-Daten v2 CKAN endpoint (`https://api.opentransportdata.swiss/ckan-api`) and dataset ID are defaults in `src/config.py`.

## CKAN API key (Secrets Manager)

The Ist-Daten v2 catalogue listing needs an opentransportdata.swiss CKAN API key. The key is stored only in AWS Secrets Manager; Terraform receives the secret ARN (`ckan_api_key_secret_arn`), grants the Lambda role `secretsmanager:GetSecretValue` on exactly that secret and passes the ARN as `CKAN_API_KEY_SECRET_ID`. Create the secret once, outside Terraform, so the value never appears in state, plans or Git. In CloudShell the key is read without echo and without shell history:

```bash
read -s CKAN_API_KEY; echo
aws secretsmanager create-secret --name mscids-dwl/<environment>/ckan-api-key --secret-string "$CKAN_API_KEY" --query ARN --output text
unset CKAN_API_KEY
```

To rotate the key, use `aws secretsmanager put-secret-value` with the same pattern; new Lambda containers pick it up automatically.

## Ist-Daten v2 CKAN sync

The `istdaten-sync` state machine keeps `raw/istdaten_v2/` in line with the catalogue:

1. `PlanSync` (`action = plan_istdaten_sync`) lists the catalogue and the existing manifests and returns every operating day that is missing or whose file hash changed, newest first, plus `stale`.
2. `LoadDays` loads each day with one Lambda invocation (`{"source": "istdaten_v2", "operating_day": "YYYY-MM-DD"}`), at most `istdaten_sync_max_concurrency` in parallel. Loading is idempotent.
3. `CheckFreshness` fails the execution (`IstdatenSourceStale`) when the newest published file is older than `ISTDATEN_V2_MAX_AGE_DAYS` (default 2), so a provider outage triggers an alarm.

Files are stored as `raw/istdaten_v2/dt=<operating day>/run=istdaten-v2-<day>-<hash12>/data.csv` with a `manifest.json` (bytes, MD5, CSV header, CKAN resource ID, URL, hash, size, timestamps). The first execution in a fresh bucket backfills the whole CKAN window (about 50 days). Optional execution input: `{"since": "2026-10-01", "max_days": 10}`. Objects written by the earlier permalink loader (`raw/istdaten_v2/dt=<ingestion date>/HHMMSS.csv`) are ignored by the sync.

## Alarms and budget

All alarms publish to the SNS topic `<project>-<environment>-alarms`. With `alarm_email` set, Terraform subscribes that address (confirm the AWS e-mail once) and creates a monthly cost budget (`monthly_budget_usd`, notifications at 80 % actual and 100 % forecasted). Alarms: loader Lambda `Errors > 0`, and `ExecutionsFailed`, `ExecutionsTimedOut`, `ExecutionsAborted > 0` for both state machines.

## Daily EventBridge preparation

The Terraform configuration contains two daily EventBridge rules: Ist-Daten-v2 starts the `istdaten-sync` state machine, municipality-weather starts the `loader` state machine. They are disabled by default with `eventbridge_schedule_enabled = false` and must remain disabled until the schedule has been reviewed in the test environment. The municipality register is a static reference snapshot and is loaded once per snapshot version or manually when the official reference changes; it is not part of the daily schedule.

When a scheduled weather execution omits `observation_date` and `run_id`, the state machine calls the Lambda's `prepare_daily` action. It derives the completed UTC day (the execution date minus one day), creates a deterministic `run_id`, and passes that date to Open-Meteo. Manual executions may continue to provide an explicit run context.

## Deployment sequence
1. Apply the existing bootstrap/state configuration with `lambda_image_uri = null` if the ECR repository does not exist yet.
2. Build and push an immutable image. The repository URL is available as `loader_ecr_repository_url`:

   ```bash
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
   docker buildx build --platform linux/amd64 --provenance=false -t <repository-url>:<immutable-tag> --push .
   ```

   The platform must match `lambda_architecture` (default `x86_64`, i.e. `linux/amd64`; CloudShell builds it natively). `--provenance=false` keeps a single-platform image manifest, which Lambda requires.

3. Set `lambda_image_uri` to the pushed tag (or digest) and apply again. Terraform then creates the Lambda function, its log group, the execution role, and the Step Functions state machines (`loader`, `istdaten-sync`).
4. Create the CKAN API key secret (see above), set `ckan_api_key_secret_arn` and `alarm_email`, and apply again. Confirm the SNS subscription e-mail.
5. Upload the immutable weather-point snapshot before starting a `municipality_weather` run, for example `reference/municipality_weather/points-v1.csv`.
6. Start both state machines manually during this phase (for the first sync, `{"max_days": 1}` is a cheap smoke test). EventBridge remains disabled until its separate plan is reviewed and applied.

## State-machine input

The workflow is intended for one source/run at a time. Batched sources should use a stable run context:

```json
{
  "source": "municipality_weather",
  "run_id": "municipality-weather-2026-11-15-points-v1",
  "execution_id": "manual-test-001",
  "observation_date": "2026-11-15",
  "point_snapshot": "points-2026-11-16-v1",
  "batch": 0,
  "batch_size": 50
}
```

The workflow loops on the Lambda response's `next_batch`. Once the last batch returns `null`, it invokes the same container with `action = "finalize"`. The final manifest is written below the deterministic `run=<run_id>` prefix. Non-run-context invocations finish after the load step and do not create a manifest.

## Validation

```bash
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
python -m pytest
black --check .
mypy src tests
```

Terraform can validate without an image. Lambda and Step Functions are intentionally conditional on `lambda_image_uri`, so the ECR repository and IAM resources can be planned before the first image push.
