# CLAUDE.md

University project (HSLU, MSCIDS): a data lake and warehouse for analysing weather- and time-related delays in Swiss public transport at municipality level. See [README.md](README.md) for the full description.

## Architecture

- Each loader in `src/loaders/` fetches raw data from one external source (weather, transport, GTFS-RT, municipality). Details: [src/loaders/README.md](src/loaders/README.md).
- `src/run.py` is the entry point. `LOADERS` maps a source name to a function returning `(bytes, extension)`; `run(source)` writes the result unchanged to S3.
- `src/storage.py` writes raw files to the S3 data lake bucket under `raw/<source>/dt=YYYY-MM-DD/HHMMSS.<ext>`. Raw data is stored as fetched, without transformation.
- `src/config.py` reads all endpoints, tokens and the bucket name from environment variables (`.env`, see `.env.example`).
- Deployed as an AWS Lambda container image. Handler: `src.run.handler`, event `{"source": "<name>"}`.

## Commands

Run everything from the repository root, inside the virtualenv (`.venv`).

```bash
python -m pip install -r requirements-dev.txt
python -m pytest                      # tests
black .                               # formatting (CI runs black --check)
mypy src tests                        # type check (CI runs it)
python -m src.run weather             # run one loader locally (needs S3_BUCKET + AWS credentials)
docker-compose up --build             # run the Lambda image locally on port 9000
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs black, mypy, pytest and a Docker build. All must pass before merging.

## Conventions

- Python 3.12, fully type-annotated (mypy is checked on `src` and `tests`).
- Format with black; docstrings use the Google style (`Args:` / `Returns:`), as in `src/storage.py`.
- Use the `logging` module (`logger = logging.getLogger(__name__)`), never `print`. Logging is set up once in `src/run.py` via `src/log.py`.
- Add a new data source in three steps: a loader in `src/loaders/`, an entry in `LOADERS` in `src/run.py`, and a test in `tests/`. Document it in `src/loaders/README.md`.
- Keep loaders thin: fetch and return, no parsing or transformation (that belongs in later pipeline stages).
- Tests must not hit the network or AWS. Mock requests and boto3. `tests/output/` is for local inspection dumps and is gitignored.

## Lambda / Docker constraints

- The Lambda filesystem is read-only except `/tmp`. Don't write files in the handler path; `setup_logging(to_file=True)` is only called from `__main__`.
- Credentials come from the execution role in Lambda and from env vars or `~/.aws` locally. Never bake them into the image.

## Secrets

`.env` is gitignored and must stay that way. Never commit tokens (for example `GTFS_RT_API_TOKEN`) or bucket credentials. Add new variables to `.env.example` with placeholders, to `src/config.py`, and to the CI env if the tests need them.
