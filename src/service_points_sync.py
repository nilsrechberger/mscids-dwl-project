"""Load the atlas service points into raw and refresh the Silver stop reference.

One call downloads the full export, and if its content changed since the last
load (MD5), it

1. stores the file unchanged as
   ``raw/service_points/dt=<UTC date>/run=service-points-<date>-<md5[:12]>/data.csv``
   with a ``manifest.json`` (every changed version is kept for lineage), and
2. rewrites ``silver/service_points/service_points.tsv``: one row per version
   of each service point with typed, English columns, the BFS municipality
   number and a flag for the newest version per stop number.

The Silver file is small (about 100k rows) and replaced as one object, so
Athena always reads a complete version. The export holds every validity period
(past and future), so the newest file is enough to map Ist-Daten of any day.
"""

import csv
import io
import json
import logging
import tempfile
from datetime import datetime, timezone
from typing import Any

import boto3

from src.config import config
from src.loaders.service_points import download_service_points
from src.storage import build_key, write_run_manifest

logger = logging.getLogger(__name__)

SOURCE = "service_points"
RAW_PREFIX = f"raw/{SOURCE}/"
SILVER_KEY = "silver/service_points/service_points.tsv"

# atlas export column -> Silver column. Required columns must exist.
REQUIRED_COLUMNS = {
    "sloid": "sloid",
    "number": "number",
    "designationOfficial": "designation_official",
    "validFrom": "valid_from",
    "validTo": "valid_to",
    "status": "status",
    "stopPoint": "is_stop_point",
    "meansOfTransport": "means_of_transport",
    "fsoNumber": "municipality_gdenr",
    "municipalityName": "municipality_name",
    "wgs84East": "wgs84_east",
    "wgs84North": "wgs84_north",
}
OPTIONAL_COLUMNS = {
    "cantonAbbreviation": "canton_abbreviation",
    "localityName": "locality_name",
}
SILVER_COLUMNS = [
    "sloid",
    "number",
    "designation_official",
    "valid_from",
    "valid_to",
    "status",
    "is_stop_point",
    "means_of_transport",
    "municipality_gdenr",
    "municipality_name",
    "canton_abbreviation",
    "locality_name",
    "wgs84_east",
    "wgs84_north",
    "is_latest_version",
    "source_run_id",
]
# Records the cookbook marks as irrelevant; kept in raw, dropped in Silver.
DROPPED_STATUSES = {"REVOKED"}


def _bucket() -> str:
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")
    return config.S3_BUCKET


def parse_date(value: str) -> str:
    """atlas dates (DD.MM.YYYY or YYYY-MM-DD) as ISO, empty if invalid."""
    value = value.strip()
    for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def _bool(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return "true"
    if normalized in {"false", "0"}:
        return "false"
    return ""


def _number(value: str) -> str:
    """Numeric text without grouping or decimals ('8503000.0' -> '8503000')."""
    value = value.strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value if value.isdigit() else ""


def _float(value: str) -> str:
    try:
        return repr(float(value.strip()))
    except ValueError:
        return ""


def _text(value: str) -> str:
    """Single-line text without tabs, safe for the TSV."""
    return " ".join(value.replace("\t", " ").split())


def _reader(handle: io.TextIOBase) -> csv.DictReader:
    sample = handle.read(65536)
    handle.seek(0)
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
    except csv.Error:
        delimiter = ";"
    return csv.DictReader(handle, delimiter=delimiter)


def build_silver_rows(
    handle: io.TextIOBase, source_run_id: str
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """
    Normalize the export to the Silver columns

    Args:
        handle: The raw CSV, opened as text
        source_run_id: Raw run the rows come from (lineage column)

    Returns:
        tuple: Silver rows and counters (input, dropped, stop points, ...)
    """
    reader = _reader(handle)
    fields = [name.strip() for name in reader.fieldnames or []]
    missing = sorted(set(REQUIRED_COLUMNS) - set(fields))
    if missing:
        raise ValueError(f"Service point export misses columns: {missing}")
    rows: list[dict[str, str]] = []
    counters = {"input_rows": 0, "dropped_status": 0, "without_municipality": 0}
    for raw in reader:
        counters["input_rows"] += 1
        record = {(key or "").strip(): (value or "") for key, value in raw.items()}
        if record["status"].strip().upper() in DROPPED_STATUSES:
            counters["dropped_status"] += 1
            continue
        row = {
            "sloid": _text(record["sloid"]),
            "number": _number(record["number"]),
            "designation_official": _text(record["designationOfficial"]),
            "valid_from": parse_date(record["validFrom"]),
            "valid_to": parse_date(record["validTo"]),
            "status": _text(record["status"]).upper(),
            "is_stop_point": _bool(record["stopPoint"]),
            "means_of_transport": _text(record["meansOfTransport"]),
            "municipality_gdenr": _number(record["fsoNumber"]),
            "municipality_name": _text(record["municipalityName"]),
            "canton_abbreviation": _text(record.get("cantonAbbreviation", "")),
            "locality_name": _text(record.get("localityName", "")),
            "wgs84_east": _float(record["wgs84East"]),
            "wgs84_north": _float(record["wgs84North"]),
            "is_latest_version": "false",
            "source_run_id": source_run_id,
        }
        if not row["municipality_gdenr"]:
            counters["without_municipality"] += 1
        rows.append(row)

    # Newest version (latest valid_from) per stop number
    latest: dict[str, int] = {}
    for index, row in enumerate(rows):
        key = row["number"] or row["sloid"]
        if not key:
            continue
        current = latest.get(key)
        if current is None or row["valid_from"] > rows[current]["valid_from"]:
            latest[key] = index
    for index in latest.values():
        rows[index]["is_latest_version"] = "true"
    counters["silver_rows"] = len(rows)
    counters["stop_numbers"] = len(latest)
    counters["stop_points"] = sum(1 for r in rows if r["is_stop_point"] == "true")
    return rows, counters


def _to_tsv(rows: list[dict[str, str]]) -> bytes:
    lines = ["\t".join(SILVER_COLUMNS)]
    lines.extend("\t".join(row[column] for column in SILVER_COLUMNS) for row in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _latest_manifest() -> dict[str, Any] | None:
    paginator = boto3.client("s3").get_paginator("list_objects_v2")
    manifests = [
        obj
        for page in paginator.paginate(Bucket=_bucket(), Prefix=RAW_PREFIX)
        for obj in page.get("Contents", [])
        if obj["Key"].endswith("/manifest.json")
    ]
    if not manifests:
        return None
    newest = max(manifests, key=lambda obj: obj["LastModified"])
    body = (
        boto3.client("s3")
        .get_object(Bucket=_bucket(), Key=newest["Key"])["Body"]
        .read()
    )
    manifest: dict[str, Any] = json.loads(body)
    return manifest


def load_service_points(force: bool = False) -> dict[str, Any]:
    """
    Download the export and, if it changed, store it and rebuild Silver

    Args:
        force: Store and rebuild even if the content did not change

    Returns:
        dict[str, Any]: Status (``loaded`` or ``unchanged``), run ID and counters
    """
    bucket = _bucket()
    s3 = boto3.client("s3")
    # /tmp is the only writable path in Lambda; the file is about 65 MB.
    with tempfile.TemporaryFile() as raw_file:
        download = download_service_points(raw_file)
        previous = _latest_manifest()
        if not force and previous and previous.get("md5") == download["md5"]:
            logger.info("Service points unchanged (md5 %s)", download["md5"])
            return {
                "status": "unchanged",
                "md5": download["md5"],
                "run_id": previous.get("run_id"),
            }

        now = datetime.now(timezone.utc)
        run_id = f"service-points-{now:%Y-%m-%d}-{download['md5'][:12]}"
        data_key = build_key(SOURCE, "csv", now=now, run_id=run_id)
        raw_file.seek(0)
        s3.upload_fileobj(
            raw_file, bucket, data_key, ExtraArgs={"ContentType": "text/csv"}
        )

        raw_file.seek(0)
        text = io.TextIOWrapper(raw_file, encoding="utf-8-sig", newline="")
        rows, counters = build_silver_rows(text, run_id)
        text.detach()
        if counters["silver_rows"] == 0:
            raise RuntimeError("Service point export produced no Silver rows")
        s3.put_object(
            Bucket=bucket,
            Key=SILVER_KEY,
            Body=_to_tsv(rows),
            ContentType="text/tab-separated-values",
        )

    write_run_manifest(
        SOURCE,
        run_id,
        {
            "source": SOURCE,
            "run_id": run_id,
            "status": "completed",
            "data_key": data_key,
            "silver_key": SILVER_KEY,
            **download,
            **counters,
            "ingested_at": now.isoformat(),
        },
        now=now,
    )
    logger.info("Loaded service points %s: %s", run_id, counters)
    return {"status": "loaded", "run_id": run_id, "data_key": data_key, **counters}
