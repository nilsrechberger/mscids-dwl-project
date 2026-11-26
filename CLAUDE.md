# CLAUDE.md

University project (HSLU, MSCIDS): a data lake and warehouse for analysing weather- and time-related delays in Swiss public transport at municipality level. See [README.md](README.md) for the full description.

## Architecture

- Each loader in `src/loaders/` fetches raw data from one external source. Production sources (see `src/sources.py`): `istdaten_v2` (opentransportdata.swiss CKAN catalogue), `municipality_weather` (Open-Meteo, batched) and `municipality` (static BFS register). `weather`, `transport` and `gtfs_rt` are legacy/baseline loaders. Details: [src/loaders/README.md](src/loaders/README.md).
- `src/run.py` is the entry point. `LOADERS` maps simple sources to a function returning `(bytes, extension)`, `BATCHED_LOADERS` holds sources loaded in several invocations. Ist-Daten v2 is handled by `src/istdaten_sync.py`, which compares the CKAN catalogue with the S3 manifests and loads missing or replaced operating days. Days older than the CKAN window are imported once from the monthly ZIP archives (`src/loaders/istdaten_archive.py`, range requests, state machine `istdaten-archive`). The weather history is backfilled one month per run (`src/weather_backfill.py`, state machine `weather-backfill`) to stay within the Open-Meteo rate limits.
- `src/storage.py` writes raw files to the S3 data lake bucket. Run-based sources use deterministic keys `raw/<source>/dt=<date>/run=<run_id>/<file>` plus a `manifest.json`; `dt` is the observation/operating day, not the ingestion date. Legacy sources without a run use `raw/<source>/dt=YYYY-MM-DD/HHMMSS.<ext>`. Raw data is stored as fetched, without transformation.
- Athena queries live in `sql/`. Raw tables contain every file below a `dt=` folder (manifests, replaced runs), so queries filter on `"$path"`; see [sql/README.md](sql/README.md).
- `src/config.py` reads all endpoints, tokens and the bucket name from environment variables (`.env`, see `.env.example`).
- Deployed as an AWS Lambda container image. Handler: `src.run.handler`, event `{"source": "<name>"}` or `{"action": "..."}` (`plan_istdaten_sync`, `prepare_daily`, `finalize`).
- Infrastructure is Terraform in `infra/` (S3, ECR, Lambda, Step Functions `loader` and `istdaten-sync`, EventBridge, alarms, budget, Glue catalog and Athena workgroup). Runtime details and deployment order: [infra/runtime.md](infra/runtime.md). AWS changes are planned and applied manually by the team in CloudShell; never run `terraform apply` or AWS write commands yourself.

## Commands

Run everything from the repository root, inside the virtualenv (`.venv`).

```bash
python -m pip install -r requirements-dev.txt
python -m pytest                      # tests
black .                               # formatting (CI runs black --check)
mypy src tests                        # type check (CI runs it)
python -m src.run weather             # run one loader locally (needs S3_BUCKET + AWS credentials)
docker-compose up --build             # run the Lambda image locally on port 9000
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false && terraform -chdir=infra validate
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs black, mypy, pytest, a Docker build and Terraform fmt/validate. All must pass before merging.

## Conventions

- Python 3.12, fully type-annotated (mypy is checked on `src` and `tests`).
- Format with black; docstrings use the Google style (`Args:` / `Returns:`), as in `src/storage.py`.
- Use the `logging` module (`logger = logging.getLogger(__name__)`), never `print`. Logging is set up once in `src/run.py` via `src/log.py`.
- Add a new data source in four steps: a loader in `src/loaders/`, a contract in `src/sources.py`, an entry in `LOADERS` (or `BATCHED_LOADERS`) in `src/run.py`, and a test in `tests/`. Document it in `src/loaders/README.md`.
- Keep loaders thin: fetch and return, no parsing or transformation (that belongs in later pipeline stages). Orchestration logic such as sync planning lives outside `src/loaders/`.
- Loads must be idempotent: deterministic run IDs, manifest written only after a complete upload.
- Tests must not hit the network or AWS. Mock requests and boto3. `tests/output/` is for local inspection dumps and is gitignored.

## Lambda / Docker constraints

- The Lambda filesystem is read-only except `/tmp`. Don't write files in the handler path; `setup_logging(to_file=True)` is only called from `__main__`.
- Large files (Ist-Daten v2, ~0.7 GB per day) are streamed to S3 and never materialized in memory.
- Credentials come from the execution role in Lambda and from env vars or `~/.aws` locally. Never bake them into the image.

## Secrets

`.env` and `*.tfvars` (except `*.tfvars.example`) are gitignored and must stay that way. Never commit tokens (for example `CKAN_API_KEY`, `GTFS_RT_API_TOKEN`), bucket credentials, account-specific values or private Terraform variables; the repository is public. In AWS, secrets live in Secrets Manager and are referenced by ARN only (e.g. `ckan_api_key_secret_arn`), never as Terraform variable values or Lambda environment values. Add new variables to `.env.example` with placeholders, to `src/config.py`, and to the CI env if the tests need them.
