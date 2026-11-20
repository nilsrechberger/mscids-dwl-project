# AWS Runtime Orchestration

This branch adds the first deployable runtime layer on top of the verified S3 data lake.

## Architecture

```text
ECR (immutable image)
        |
        v
Lambda container (src.run.handler)
        |  S3 read reference/ and raw/municipality
        |  S3 write raw/ and deterministic manifests
        v
Step Functions Standard workflow
  InvokeBatch -> HasNextBatch -> PrepareNextBatch (loop)
                           \-> FinalizeManifest -> Succeeded
```

The execution role is intentionally limited to CloudWatch logging and the existing loader S3 policy. The S3 policy reads the municipality/weather reference area and the municipality input, lists the relevant prefixes, and writes raw objects. API tokens must not be stored in Terraform variables or Lambda environment variables; use Secrets Manager/SSM and add the retrieval contract in a separate change.

The `municipality_weather` loader accepts both local paths and an immutable `s3://bucket/key` CSV URI. Configure `municipality_weather_points_uri` with the versioned object under `reference/`. The `point_snapshot` field in the run event is retained in the final manifest for lineage and is validated as part of the run contract.


The Lambda also requires these non-secret public endpoints in `lambda_environment`:

```hcl
MUNICIPALITY_XLSX    = "https://www.agvchapp.bfs.admin.ch/de/state/results/xls?SnapshotDate=01.01.2026"
ISTDATEN_V2_ENDPOINT = "https://data.opentransportdata.swiss/dataset/ist-daten-v2/permalink"
```

API tokens and other secrets must not be committed; use Secrets Manager or SSM for those values.

## Daily EventBridge preparation

The Terraform configuration contains two daily EventBridge rules for Ist-Daten-v2 and municipality-weather. They are disabled by default with `eventbridge_schedule_enabled = false` and must remain disabled until the schedule has been reviewed in the test environment. The municipality register is a static reference snapshot and is loaded once per snapshot version or manually when the official reference changes; it is not part of the daily schedule.

When a scheduled weather execution omits `observation_date` and `run_id`, the state machine calls the Lambda's `prepare_daily` action. It derives the completed UTC day (the execution date minus one day), creates a deterministic `run_id`, and passes that date to Open-Meteo. Manual executions may continue to provide an explicit run context.

## Deployment sequence
1. Apply the existing bootstrap/state configuration with `lambda_image_uri = null` if the ECR repository does not exist yet.
2. Build and push an immutable image. The repository URL is available as `loader_ecr_repository_url`:

   ```bash
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
   docker buildx build --platform linux/arm64 -t <repository-url>:<immutable-tag> --push .
   ```

3. Set `lambda_image_uri` to the pushed tag (or digest) and apply again. Terraform then creates the Lambda function, its log group, the execution role, and the Step Functions state machine.
4. Upload the immutable weather-point snapshot before starting a `municipality_weather` run, for example `reference/municipality_weather/points-v1.csv`.
5. Start the state machine manually during this phase. EventBridge remains disabled until its separate plan is reviewed and applied.

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
