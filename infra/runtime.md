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

All alarms publish to the SNS topic `<project>-<environment>-alarms`. With `alarm_emails` set, Terraform subscribes every address (each recipient confirms the AWS e-mail once) and creates a monthly cost budget (`monthly_budget_usd`, notifications at 80 % actual and 100 % forecasted). Alarms: loader Lambda `Errors > 0`, and `ExecutionsFailed`, `ExecutionsTimedOut`, `ExecutionsAborted > 0` for every state machine.

## Ist-Daten v2 archive import

The `istdaten-archive` state machine imports days older than the CKAN window from the monthly ZIP archives (public, from 2025-07). It is started manually and never scheduled:

```json
{"since": "2025-08-01", "until": "2026-10-31", "max_days": 31}
```

1. `PlanImport` (`action = plan_istdaten_archive`) reads the central directory of every monthly ZIP in the range (a few small range requests per month) and lists each day without any loaded version, oldest first. Months whose archive is not published yet are reported in `missing_months`.
2. `LoadDays` loads each day with one Lambda invocation (`{"source": "istdaten_v2", "operating_day": "...", "archive_month": "YYYY-MM"}`), at most `istdaten_archive_max_concurrency` (default 3) in parallel. The Lambda streams the ZIP member with range requests, decompresses it on the fly and verifies its CRC32; a corrupt member fails before the manifest is written.

Imported days use the same key layout as the CKAN sync with the CRC32 as version marker (`run=istdaten-v2-<day>-<crc32>`); their manifest has `origin: archive` and the ZIP URL and member. A day that already has any version (for example from CKAN) is skipped, so restarting the import is safe. The per-day results are not kept in the execution output (state size limit); the manifests in S3 are the record. Start with `max_days` in the test environment and check the result with Athena before importing the full range in prod.

## Municipality weather backfill

The `weather-backfill` state machine loads the municipality weather history from the Open-Meteo archive API. The free tier allows 10,000 calls per day, 5,000 per hour and 600 per minute, and Open-Meteo counts one location as one call per two weeks of data. The daily run already costs about one call per point (about 2,070). Loading the history day by day would cost one call per point and day; one calendar month per request costs about 2.2 calls per point instead. The backfill therefore loads one month per run and waits between the months. It is started manually and never scheduled:

```json
{"since": "2025-08-01", "until": "2026-11-21", "point_snapshot": "points-v1"}
```

Optional: `batch_size` (default 50) and `interval_hours` (default 24). `until` must be the day before the first daily weather run, so the two never overlap.

1. `PlanMonths` (`action = plan_weather_backfill`) splits the range into calendar months, skips months whose final manifest is `completed` and gives every month after the first a `wait_seconds` of `interval_hours`.
2. `LoadMonths` loads the months one after another: wait, then the same batch loop as the `loader` state machine with `end_date` in the event and a pause of `weather_backfill_batch_wait_seconds` (default 15) between batches, then `finalize`. A month whose final manifest is not `completed` fails the execution (`WeatherMonthIncomplete`). HTTP errors such as 429 are retried after 5, 10 and 20 minutes.

A month with 2,071 points costs about 4,600 calls in about 15 minutes, so start the execution at a time of day well away from the daily schedule (06:00 UTC) and keep `interval_hours` at 24. Each month is stored as a normal `municipality_weather` run under `dt=<first day of the month>` with run ID `municipality-weather-<first>-<last>-<point_snapshot>`; the manifest has `end_date`, and the hourly timestamps in the responses identify the days. Restarting with the same input skips completed months.

## Silver Ist-Daten build

The `silver-istdaten` state machine keeps the Iceberg table `mscids_dwl_<environment>_silver.istdaten` in line with the raw files (see [sql/README.md](../sql/README.md)):

1. `PlanDays` (`action = plan_silver_istdaten`) lists the newest raw run per operating day (latest `manifest.json`) and the build markers under `silver/_state/istdaten/`, and returns the days that are missing or were built from an older run. It creates the table on first use.
2. `BuildDays` rebuilds each day (`action = build_silver_istdaten`), at most `silver_max_concurrency` (default 3) in parallel: delete the old marker, `DELETE` the day, `INSERT` it from the raw file, count the rows, write the new marker. Failures (for example Iceberg commit conflicts) are retried; a rebuild is idempotent.

A daily EventBridge rule (`silver_schedule_expression`, default 08:00 UTC, after the 06:00 sync) starts it with `{}`. Manual input: `{"since": "2025-08-01", "until": "2025-08-31", "max_days": 5}`; `{"force": true, ...}` rebuilds days that are up to date, for example after a change of the SQL. One day scans about 0.6 GB of CSV (about 0.003 USD); the first build of all days about 290 GB (about 1.50 USD).

## Stop reference (service points)

A weekly EventBridge rule (`service_points_schedule_expression`, default Monday 05:00 UTC) invokes the Lambda with `{"source": "service_points"}`. It downloads the atlas full export (about 65 MB, public, no key) and, if the MD5 changed, stores it under `raw/service_points/` and rewrites `silver/service_points/service_points.tsv`, which the Glue table `mscids_dwl_<environment>_silver.service_points` reads. Unchanged content returns `{"status": "unchanged"}`. Manual run: `aws lambda invoke` with `{"source": "service_points"}` (add `"force": true` to reload). Mapping queries: [sql/silver/stop_municipality.sql](../sql/silver/stop_municipality.sql).

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
4. Create the CKAN API key secret (see above), set `ckan_api_key_secret_arn` and `alarm_emails`, and apply again. Each recipient confirms the SNS subscription e-mail.
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
