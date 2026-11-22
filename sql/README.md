# SQL (Athena)

Queries on the data lake through the Glue Data Catalog and Athena. The catalog and the workgroup are Terraform resources in [`infra/catalog.tf`](../infra/catalog.tf):

| Resource | Name |
|---|---|
| Glue database (raw layer) | `mscids_dwl_<environment>_raw` |
| Raw Ist-Daten table | `istdaten_v2` (all columns `string`, partition `dt` via partition projection) |
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
