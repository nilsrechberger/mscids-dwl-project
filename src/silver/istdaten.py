"""Build the Silver Ist-Daten table (Iceberg) one operating day at a time.

Every day is built from exactly one raw file: the newest loaded version of
that day (the run whose ``manifest.json`` was written last; a replaced CKAN
file therefore wins over the older one). A build deletes the day from the
Silver table and inserts it again from that file, so it can be repeated any
number of times. After a successful build a small marker object
``silver/_state/istdaten/dt=<day>/run=<run_id>.json`` records which raw run the
day was built from. The planner compares these markers with the newest raw
runs and lists the days that are missing or out of date.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import boto3

from src.config import config
from src.silver.athena import first_value, run_query
from src.storage import RUN_ID_PATTERN

logger = logging.getLogger(__name__)

RAW_PREFIX = "raw/istdaten_v2/"
STATE_PREFIX = "silver/_state/istdaten/"
SILVER_PREFIX = "silver/istdaten/"
SQL_DIR = Path(__file__).parent / "sql"

_RAW_MANIFEST = re.compile(
    r"^raw/istdaten_v2/dt=(\d{4}-\d{2}-\d{2})/run=([A-Za-z0-9._-]+)/manifest\.json$"
)
_MARKER = re.compile(
    r"^silver/_state/istdaten/dt=(\d{4}-\d{2}-\d{2})/run=([A-Za-z0-9._-]+)\.json$"
)
_IDENTIFIER = re.compile(r"^[a-z0-9_]+$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_MD5 = re.compile(r"^[0-9a-f]{32}$")
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


@dataclass(frozen=True)
class RawVersion:
    """The raw run a Silver day is built from."""

    operating_day: str
    run_id: str
    manifest_key: str


def _bucket() -> str:
    if not config.S3_BUCKET or not _BUCKET.match(config.S3_BUCKET):
        raise RuntimeError("S3_BUCKET is not set or invalid")
    return config.S3_BUCKET


def _database(value: str | None, name: str) -> str:
    if not value or not _IDENTIFIER.match(value):
        raise RuntimeError(f"{name} is not set or not a valid Glue name")
    return value


def render_sql(template: str, values: dict[str, str]) -> str:
    """
    Fill a SQL template from ``src/silver/sql``

    Comment lines are dropped (Athena DDL does not accept them), and every
    ``{name}`` placeholder must have a value. The values are validated by the
    callers, so no user input reaches the statement unchecked.
    """
    text = (SQL_DIR / template).read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("--")]
    sql = "\n".join(lines).strip().rstrip(";")
    missing = sorted(set(_PLACEHOLDER.findall(sql)) - set(values))
    if missing:
        raise ValueError(f"{template}: no value for {missing}")
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], sql)


def _list_keys(prefix: str) -> list[dict[str, Any]]:
    paginator = boto3.client("s3").get_paginator("list_objects_v2")
    return [
        dict(obj)
        for page in paginator.paginate(Bucket=_bucket(), Prefix=prefix)
        for obj in page.get("Contents", [])
    ]


def newest_raw_versions() -> dict[str, RawVersion]:
    """Newest loaded run per operating day (latest manifest.json)."""
    newest: dict[str, tuple[datetime, RawVersion]] = {}
    for obj in _list_keys(RAW_PREFIX):
        match = _RAW_MANIFEST.match(obj["Key"])
        if not match:
            continue
        day, run_id = match.groups()
        version = RawVersion(day, run_id, obj["Key"])
        modified: datetime = obj["LastModified"]
        if day not in newest or modified > newest[day][0]:
            newest[day] = (modified, version)
    return {day: version for day, (_, version) in newest.items()}


def built_versions() -> dict[str, set[str]]:
    """Raw run IDs recorded by the Silver build markers, per day."""
    built: dict[str, set[str]] = {}
    for obj in _list_keys(STATE_PREFIX):
        match = _MARKER.match(obj["Key"])
        if match:
            built.setdefault(match.group(1), set()).add(match.group(2))
    return built


def ensure_table() -> None:
    """Create the Iceberg table if it does not exist yet."""
    run_query(
        render_sql(
            "istdaten_create.sql",
            {
                "silver_db": _database(
                    config.GLUE_SILVER_DATABASE, "GLUE_SILVER_DATABASE"
                ),
                "silver_location": f"s3://{_bucket()}/{SILVER_PREFIX}",
            },
        )
    )


def plan_silver_istdaten(
    since: str | None = None,
    until: str | None = None,
    max_days: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    List the operating days whose Silver data is missing or out of date

    Args:
        since: First day to consider (YYYY-MM-DD), default: all raw days
        until: Last day to consider (YYYY-MM-DD), default: all raw days
        max_days: Build at most this many days (oldest first)
        force: Rebuild every day in the range, even if it is up to date

    Returns:
        dict[str, Any]: ``items`` (days to build, oldest first), ``pending``
        and ``up_to_date`` counts
    """
    start = date.fromisoformat(since) if since else date.min
    end = date.fromisoformat(until) if until else date.max
    if start > end:
        raise ValueError("since must not be after until")
    newest = newest_raw_versions()
    built = built_versions()
    days = [
        day
        for day in sorted(newest)
        if start <= date.fromisoformat(day) <= end
        and (force or newest[day].run_id not in built.get(day, set()))
    ]
    in_range = sum(1 for day in newest if start <= date.fromisoformat(day) <= end)
    items = days[:max_days] if max_days is not None else days
    if items:
        ensure_table()
    logger.info(
        "Silver Ist-Daten: %d of %d days to build (%d in this execution)",
        len(days),
        in_range,
        len(items),
    )
    return {
        "items": items,
        "pending": len(days),
        "up_to_date": in_range - len(days),
    }


def _read_manifest(key: str) -> dict[str, Any]:
    body = boto3.client("s3").get_object(Bucket=_bucket(), Key=key)["Body"].read()
    manifest: dict[str, Any] = json.loads(body)
    return manifest


def build_day(operating_day: str) -> dict[str, Any]:
    """
    Rebuild one operating day of silver.istdaten from its newest raw run

    Args:
        operating_day: YYYY-MM-DD

    Returns:
        dict[str, Any]: Source run, row count and scanned bytes
    """
    date.fromisoformat(operating_day)
    bucket = _bucket()
    raw_db = _database(config.GLUE_RAW_DATABASE, "GLUE_RAW_DATABASE")
    silver_db = _database(config.GLUE_SILVER_DATABASE, "GLUE_SILVER_DATABASE")
    version = newest_raw_versions().get(operating_day)
    if version is None:
        raise LookupError(f"No raw Ist-Daten run for {operating_day}")
    manifest = _read_manifest(version.manifest_key)
    data_key = manifest.get("data_key", "")
    md5 = manifest.get("md5", "")
    expected_prefix = f"{RAW_PREFIX}dt={operating_day}/run={version.run_id}/"
    if not data_key.startswith(expected_prefix) or not data_key.endswith(".csv"):
        raise ValueError(f"Unexpected data_key in {version.manifest_key}: {data_key}")
    if not _MD5.match(md5) or not RUN_ID_PATTERN.fullmatch(version.run_id):
        raise ValueError(f"Invalid md5 or run_id in {version.manifest_key}")

    # Drop the old markers first: if the rebuild fails half-way, the planner
    # sees the day as not built and tries again.
    s3 = boto3.client("s3")
    for obj in _list_keys(f"{STATE_PREFIX}dt={operating_day}/"):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])

    delete = run_query(
        f"DELETE FROM {silver_db}.istdaten "
        f"WHERE operating_date = DATE '{operating_day}'"
    )
    insert = run_query(
        render_sql(
            "istdaten_insert.sql",
            {
                "silver_db": silver_db,
                "raw_db": raw_db,
                "operating_day": operating_day,
                "source_path": f"s3://{bucket}/{data_key}",
                "source_run_id": version.run_id,
                "source_md5": md5,
            },
        )
    )
    count = run_query(
        f"SELECT count(*) FROM {silver_db}.istdaten "
        f"WHERE operating_date = DATE '{operating_day}'"
    )
    rows = int(first_value(count["query_execution_id"]) or 0)
    if rows == 0:
        raise RuntimeError(f"Silver build of {operating_day} produced no rows")

    result = {
        "operating_day": operating_day,
        "source_run_id": version.run_id,
        "source_data_key": data_key,
        "source_md5": md5,
        "rows": rows,
        "data_scanned_bytes": delete["data_scanned_bytes"]
        + insert["data_scanned_bytes"]
        + count["data_scanned_bytes"],
        "query_execution_ids": [
            delete["query_execution_id"],
            insert["query_execution_id"],
            count["query_execution_id"],
        ],
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    s3.put_object(
        Bucket=bucket,
        Key=f"{STATE_PREFIX}dt={operating_day}/run={version.run_id}.json",
        Body=json.dumps(result).encode("utf-8"),
        ContentType="application/json",
    )
    logger.info("Built silver.istdaten %s: %d rows", operating_day, rows)
    return result
