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
├── .github/workflows/ci.yml            # CI: black, mypy, pytest, Docker build
├── .env.example                        # Example .env file
├── .gitignore                          # Git ignore file
├── CLAUDE.md                           # Project instructions for Claude Code
├── Dockerfile                          # AWS Lambda container image
├── docker-compose.yml                  # Run the Lambda image locally
├── mypy.ini                            # Mypy config
├── pytest.ini                          # Pytest config
├── README.md                           # Project documentation
├── requirements.txt                    # Runtime dependencies
├── requirements-dev.txt                # Dev dependencies (pytest, black, mypy)
├── src
│   ├── config.py                       # Reads endpoints, tokens and bucket from env
│   ├── log.py                          # Logging setup
│   ├── run.py                          # Entry point and Lambda handler
│   ├── storage.py                      # Writes raw files to S3
│   └── loaders                         # Data loaders (see loaders/README.md)
└── tests                               # Pytest tests
    ├── conftest.py
    ├── test_gtfs_rt.py
    ├── test_municipality.py
    ├── test_run.py
    ├── test_transport.py
    └── test_weather.py
```

## Data Lake Layout

Each loader fetches one source and `src/run.py` writes the response unchanged to S3:

```text
s3://<S3_BUCKET>/raw/<source>/dt=YYYY-MM-DD/HHMMSS.<ext>
```

`<source>` is one of `weather`, `transport`, `gtfs_rt`, `municipality`. Parsing and transformation happen in later pipeline stages.

> Known limitation: the weather location and date range and the transport query ("Basel") are currently hardcoded in the loaders.

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

The loaders are packaged as an AWS Lambda container image (see `Dockerfile`). The handler is `src.run.handler` and expects an event like `{"source": "weather"}`, where the source is one of `weather`, `transport`, `gtfs_rt`, `municipality`.

### Run locally

Fill in `.env` and make AWS credentials available (environment variables or `~/.aws`), then start the Lambda Runtime Interface Emulator:

```bash
docker-compose up --build

curl -XPOST http://localhost:9000/2015-03-31/functions/function/invocations \
  -d '{"source": "weather"}'
```

### Deploy

1. Create an ECR repository, then build and push the image. Add `--platform linux/arm64` if the function runs on arm64.
2. Create the Lambda function from the image.
   - Execution role needs `s3:PutObject` on the data lake bucket.
   - Set the variables from `.env.example` as environment variables (keep `GTFS_RT_API_TOKEN` in Secrets Manager or SSM).
   - Use a timeout well above the 3 s default and at least 512 MB memory.
3. Create one EventBridge Scheduler rule per source, each passing `{"source": "<name>"}` as input.

# Contact

- Nils Rechberger: nils.rechberger@stud.hslu.ch
- Joel Rieser: joel.rieser@stud.hslu.ch
- Timo Schildknecht: timo.schildknecht@stud.hslu.ch
