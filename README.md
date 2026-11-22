# On Time in Every Municipality?
A Data Lake and Data Warehouse for Analysing Weather- and Time-Related Delays in Swiss Public Transport at Municipality Level.

```text
  ═══ Line 2    ─── Line 3    │ Line 4    ║ Line 7    ● Station    ≈ Lake

                           [4] [7]
                            │   ║
                            ●   ●  Nordring
                            │   ║
                Lindenplatz ●   ●
                            │   ║
[2]═══●══════════●══════════╪═══╬══════════●══════════●═══[2]
[3]───●──────────●──────────┼───╫──────────●──────────●───[3]
   Westhof    Kreuzweg      │   ║ Zentrum Markt     Ostpark
                            │   ║
               Brückenplatz ●   ●
                            │   ╚═══════════╗
                            │               ║   ≈≈≈≈≈≈
                            ●  Parkring     ●  ≈≈≈≈≈≈≈≈≈
                            │               ║ ≈≈≈≈≈≈≈≈≈≈≈≈
                            │      Seeblick ● ≈≈≈≈ SEE ≈≈≈≈
                            ●  Südbahnhof   ║  ≈≈≈≈≈≈≈≈≈≈≈
                            │               ║   ≈≈≈≈≈≈≈≈≈
                           [4]             [7]
```

## Project Structure

```bash
.
├── .github/workflows/ci.yml            # CI: black, mypy, pytest, Docker build, Terraform fmt/validate
├── .env.example                        # Example .env file (placeholders only)
├── CLAUDE.md                           # Project instructions for Claude Code
├── Dockerfile                          # AWS Lambda container image
├── docker-compose.yml                  # Run the Lambda image locally
├── requirements.txt                    # Runtime dependencies
├── requirements-dev.txt                # Dev dependencies (pytest, black, mypy)
├── infra                               # Terraform: S3, ECR, Lambda, Step Functions, EventBridge, alarms, Glue/Athena
│   ├── README.md                       # IaC overview and key contract
│   ├── runtime.md                      # Runtime, secrets, deployment sequence
│   └── environments/*.tfvars.example   # Example variables (real *.tfvars are gitignored)
├── src
│   ├── config.py                       # Reads endpoints, tokens and bucket from env
│   ├── http.py                         # Shared HTTP session with retries
│   ├── istdaten_sync.py                # Ist-Daten v2 CKAN sync (plan and load days)
│   ├── log.py                          # Logging setup
│   ├── run.py                          # Entry point and Lambda handler
│   ├── runs.py                         # Run-context validation and manifest finalization
│   ├── sources.py                      # Source contracts (production vs legacy)
│   ├── storage.py                      # Writes raw files and manifests to S3
│   └── loaders                         # Data loaders (see loaders/README.md)
├── sql                                 # Athena queries on the Glue catalog (see sql/README.md)
├── scripts                             # Local Silver/Gold and reference-data tooling
├── utils                               # Early cost estimator (GTFS-RT era, not maintained)
└── tests                               # Pytest tests (no network, no AWS)
```

## Data Lake Layout

Each loader fetches one source and `src/run.py` writes the response unchanged to S3:

```text
s3://<S3_BUCKET>/raw/<source>/dt=YYYY-MM-DD/HHMMSS.<ext>
```

When a run context is supplied, deterministic keys are used instead:

```text
s3://<S3_BUCKET>/raw/<source>/dt=YYYY-MM-DD/run=<run_id>/part0000.<ext>
s3://<S3_BUCKET>/raw/<source>/dt=YYYY-MM-DD/run=<run_id>/manifest_part0000.json
s3://<S3_BUCKET>/raw/<source>/dt=YYYY-MM-DD/run=<run_id>/manifest.json
```

`<source>` includes `istdaten_v2`, `municipality_weather`, `municipality`, `weather`, `transport` and `gtfs_rt`. Ist-Daten v2 is synced from the opentransportdata.swiss CKAN catalogue: every missing or replaced daily file is streamed unchanged to `raw/istdaten_v2/dt=<operating day>/run=<version>/data.csv` with a manifest, without loading the complete file into memory (`python -m src.run istdaten_v2` loads the newest day locally). Parsing and transformation happen in later pipeline stages.

## Run contract and local validation

Production-style batched events use one stable `run_id` for all batches. The Lambda does not generate a new ID per invocation. A `municipality_weather` event must contain `run_id`, `execution_id`, `observation_date` and `point_snapshot`:

```json
{
  "source": "municipality_weather",
  "run_id": "municipality-weather-2026-11-15-points-v1",
  "execution_id": "local-smoke-test",
  "observation_date": "2026-11-15",
  "point_snapshot": "points-2026-11-16-v1",
  "batch": 0,
  "batch_size": 50
}
```

Every completed batch receives a `manifest_partXXXX.json`. `src.runs.finalize_run()` aggregates these manifests. Silver processing should call `require_completed_run()` and only continue when the final manifest has `status = completed`.

## Ist-Daten v2 municipality pipeline

The scripts below are the locally validated implementation for the official Ist-Daten v2 daily files. Bronze keeps the source CSV unchanged; Silver normalizes the German source columns and adds delay-quality fields; Gold aggregates transport and weather by BFS municipality and operating date.

The local pipeline performs the following steps:

```text
Ist-Daten v2 daily CSV (Bronze)
        ↓
English Silver normalization and delay quality
        ↓
GTFS Static stops.txt (SLOID/BPUIC matching)
        ↓
BFS municipality boundaries (GeoJSON, 01.01.2026)
        ↓
Municipality-level transport daily aggregates
        ↓
Stop-weighted municipality weather points and Open-Meteo batches
        ↓
Gold `municipality_daily`
```

The raw Ist-Daten and weather values are never deleted because of quality issues. Bronze keeps the source representation unchanged. Silver adds fields such as `delay_raw_seconds`, `delay_quality` and `delay_exclusion_reason`. Gold queries apply metric-specific filters, for example using only `REAL` and plausible values for measured-delay averages.

The current local validation used 2,139,124 Ist-Daten rows from 14 November 2026, matched 99.839% of transport rows to GTFS stops, assigned 2,094,022 rows to BFS municipalities, and fetched 49,704 hourly weather rows for 2,071 municipalities. Weather is represented by the mean coordinates of GTFS stops assigned to each municipality and is joined using `gdenr + date`.

Useful local commands from the repository root are:

```bash
# Tests and static checks
python -m pytest
black scripts tests
mypy src tests

# Profile and validate local source data
python scripts/profile_istdaten.py --input <istdaten.csv> --output-dir <profile-dir>
python scripts/profile_delay_quality.py --input <istdaten.csv> --output <delay-profile.json>
python scripts/match_istdaten_stops.py --istdaten <istdaten.csv> --stops <stops.csv> --output-dir <dir>   # stop match rate (RQ4)

# Reference data (versioned snapshots under reference/ in S3)
python scripts/extract_gtfs_stops.py --zip <gtfs.zip> --output <stops.csv>
python scripts/join_stops_municipalities.py --stops <stops.csv> --boundaries <municipalities.geojson> --output <stops_municipalities.csv>
python scripts/build_municipality_weather_points.py --stops <stops_municipalities.csv> --output <municipality_weather_points.csv>

# Silver and Gold transformations
python -m scripts.normalize_istdaten_silver --input <istdaten.csv> --output <silver.csv>
python -m scripts.join_istdaten_municipalities --silver <silver.csv> --stops <stops_municipalities.csv> --output <mapped.csv>
python scripts/aggregate_silver_municipality_daily.py --input <mapped.csv> --output <transport_daily.csv>
python scripts/fetch_municipality_weather.py --points <points.csv> --output <weather_hourly.csv> --start-date <d> --end-date <d>   # local only; AWS uses the municipality_weather loader
python scripts/aggregate_weather_daily.py --input <weather_hourly.csv> --output <weather_daily.csv>
python scripts/join_municipality_daily.py --transport <transport_daily.csv> --weather <weather_daily.csv> --output <municipality_daily.csv>

# Production run-contract smoke test; no AWS and no API call
python -m scripts.smoke_test_run_contract \
  --points <municipality_weather_points.csv> \
  --run-id municipality-weather-2026-11-15-points-v1 \
  --execution-id local-smoke-test \
  --observation-date 2026-11-15 \
  --point-snapshot points-2026-11-16-v1 \
  --batch-size 50
```

The scripts under `scripts/` are intentionally local spike tooling. Large source files, downloaded GTFS archives, GeoJSON boundaries and generated outputs belong under `.work/` and must not be committed.

The AWS runtime is described in [infra/runtime.md](infra/runtime.md): Terraform provisions the ECR repository, the Lambda container, the Step Functions workflows (municipality weather batches, Ist-Daten v2 CKAN sync), the daily EventBridge schedules, alarms and a cost budget. Generated source files and outputs belong under `.work/` and must not be committed.

## Setup

### 1. Clone this repository

```bash
git clone https://github.com/nilsrechberger/mscids-dwl-project.git

cd mscids-dwl-project
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv

# For Windows
.venv\Scripts\activate 

# For Mac / Linux
source .venv/bin/activate
```

### 3. Configure the environment

```bash
cp .env.example .env   # then fill in the tokens and the bucket name
```

### 4. Install the dependencies

```bash
python -m pip install -r requirements.txt

# For development (pytest, black, mypy)
python -m pip install -r requirements-dev.txt
```

Run everything from the repository root:

```bash
python -m pytest              # unit tests (mocked, no network)
python -m pytest -m network   # also dumps real API data to tests/output/
black .                       # formatting
mypy src tests                # type check
python -m src.run weather     # run one loader (needs S3_BUCKET and AWS credentials)
```

## Docker / AWS Lambda

The loaders are packaged as an AWS Lambda container image (see `Dockerfile`). The handler is `src.run.handler`. Production-style municipality-weather events contain `source`, `run_id`, `execution_id`, `observation_date`, `point_snapshot`, `batch` and `batch_size`.

### Run locally

Fill in `.env` and make AWS credentials available (environment variables or `~/.aws`), then start the Lambda Runtime Interface Emulator:

```bash
docker-compose up --build

curl -XPOST http://localhost:9000/2015-03-31/functions/function/invocations \
  -d '{"source": "weather"}'
```

### Deploy

Deployment is managed with Terraform in [infra/](infra/). Follow [infra/runtime.md](infra/runtime.md) for the sequence (image build, apply, secret, smoke tests, schedules). The CKAN API key is stored in AWS Secrets Manager and only referenced by ARN; it never goes into Terraform variables, Lambda environment variables or Git.

# Contact

- Nils Rechberger: nils.rechberger@stud.hslu.ch
- Joel Rieser: joel.rieser@stud.hslu.ch
- Timo Schildknecht: timo.schildknecht@stud.hslu.ch
