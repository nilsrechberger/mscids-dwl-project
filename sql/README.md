# SQL (Athena)

Queries on the data lake through the Glue Data Catalog and Athena. The catalog and the workgroup are Terraform resources in [`infra/catalog.tf`](../infra/catalog.tf):

| Resource | Name |
|---|---|
| Glue database (raw layer) | `mscids_dwl_<environment>_raw` |
| Raw Ist-Daten table | `istdaten_v2` (all columns `string`, partition `dt` via partition projection) |
| Glue database (Silver layer) | `mscids_dwl_<environment>_silver` |
| Silver Ist-Daten table | `istdaten` (Iceberg, Parquet, partitioned by `day(operating_date)`; created by the Lambda, see below) |
| Silver stop reference | `service_points` (TSV, one row per validity period of an atlas service point, written by the `service_points` load) |
| Athena workgroup | `mscids-dwl-<environment>` (results in `s3://<bucket>/athena-results/`, expire after 30 days, at most 50 GB scanned per query) |

## Raw tables and `"$path"`

Raw tables describe the files exactly as the loaders store them. One `dt=` folder can contain more than the current data file:

- the run `manifest.json` next to `data.csv`,
- older `run=` folders when CKAN replaced a daily file,
- in the test bucket, files of the earlier permalink loader (`dt=<ingestion date>/HHMMSS.csv`).

Athena reads every file below a partition, so queries filter on the `"$path"` pseudo-column:

- `"$path" LIKE '%/run=istdaten-v2-%/data.csv'` drops manifests and permalink files (enough for exploration);
- `"$path" = 's3://<bucket>/' || <data_key from manifest.json>` selects exactly one version per day. The Silver build uses this, so every Silver partition traces back to one raw file and its MD5.

Always restrict `dt`. One day of Ist-Daten scans about 0.7 GB (about 0.004 USD), the whole 50-day CKAN window about 34 GB (about 0.17 USD). Parquet in Silver will make repeated analysis much cheaper.

## Files

- [`exploration/istdaten_v2.sql`](exploration/istdaten_v2.sql): first look at the raw data (files per day, sample rows, volume, status mix, delay distribution, punctuality by means of transport).
- [`silver/istdaten_checks.sql`](silver/istdaten_checks.sql): checks and example analyses on `silver.istdaten`, plus the Iceberg maintenance statements.
- [`silver/stop_municipality.sql`](silver/stop_municipality.sql): stop -> municipality mapping, coverage checks and an example delay aggregation per municipality.

## Silver Ist-Daten

`silver.istdaten` holds one row per stop event with English column names, typed values and the delay quality rules of [`scripts/delay_quality.py`](../scripts/delay_quality.py) (`delay_quality`, `*_delay_seconds`, `*_usable_for_real_delay` = valid and status `REAL`). Timestamps are Swiss local time without a time zone, as in the source. Every day is built from exactly one raw file, the newest loaded run of that day; `source_run_id` and `source_md5` link each row to it.

The statements are templates in [`src/silver/sql/`](../src/silver/sql) and run in the Lambda (`src/silver/istdaten.py`): `CREATE TABLE IF NOT EXISTS` (Iceberg), then per day `DELETE` + `INSERT ... SELECT` from the raw table with the exact `"$path"`, then a row count. A marker `silver/_state/istdaten/dt=<day>/run=<run_id>.json` records the build, so the daily run only rebuilds new or replaced days. Column names follow the spike script `scripts/normalize_istdaten_silver.py`, except `circulation_id` (`UMLAUF_ID`, called `run_id` there, which would clash with the ingestion run ID) and the added `is_pass_through`, `source_run_id` and `source_md5`.

## Stop -> municipality

`silver.service_points` comes from the atlas export `service-point-v2` (full CSV, updated daily, no key). It holds every validity period of each service point, so the newest export maps Ist-Daten of any day. Ist-Daten join on the 7-digit BPUIC (`istdaten.stop_id_bpuic = service_points.number`) and the version valid on the operating day (`operating_date BETWEEN valid_from AND valid_to`); `is_latest_version` is the fallback for stops without a matching period. `municipality_gdenr` is the BFS number (`fsoNumber`) of that version. Records with status `REVOKED` are dropped. After municipality mergers an older version can carry a former BFS number, while the weather points use the current snapshot; check this before joining weather (query 2 in the file).
