"""Keep raw/istdaten_v2 in sync with the CKAN catalogue.

Every daily file is stored under its operating day and a run ID that encodes
the file version (the CKAN content hash):

    raw/istdaten_v2/dt=<operating day>/run=istdaten-v2-<day>-<hash12>/data.csv
    raw/istdaten_v2/dt=<operating day>/run=istdaten-v2-<day>-<hash12>/manifest.json

The manifest is written only after a complete upload, so its existence marks a
loaded version. Planning compares the catalogue against these manifests and
returns every day that is missing or whose file was replaced by the provider.
"""

import hashlib
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, BinaryIO, cast

import boto3
from botocore.exceptions import ClientError

from src.config import config
from src.loaders.istdaten_v2 import (
    IstdatenResource,
    find_resource,
    list_istdaten_resources,
    open_resource_stream,
)
from src.storage import build_key, write_run_manifest

logger = logging.getLogger(__name__)

SOURCE = "istdaten_v2"
_MANIFEST_KEY = re.compile(
    r"^raw/istdaten_v2/dt=(\d{4}-\d{2}-\d{2})/"
    r"run=istdaten-v2-\1-([0-9a-z]{1,12})/manifest\.json$"
)
_HEADER_LIMIT = 64 * 1024


class _MeteredStream:
    """Read-only stream wrapper that counts bytes, hashes and keeps the header."""

    def __init__(self, raw: BinaryIO) -> None:
        self._raw = raw
        self.bytes_read = 0
        self._md5 = hashlib.md5(usedforsecurity=False)
        self._head = bytearray()

    def read(self, size: int = -1) -> bytes:
        chunk = self._raw.read(size)
        if chunk:
            self.bytes_read += len(chunk)
            self._md5.update(chunk)
            if len(self._head) < _HEADER_LIMIT:
                self._head.extend(chunk[: _HEADER_LIMIT - len(self._head)])
        return chunk

    @property
    def md5(self) -> str:
        return self._md5.hexdigest()

    @property
    def header(self) -> str:
        first_line = bytes(self._head).split(b"\n", 1)[0]
        return first_line.decode("utf-8-sig", errors="replace").strip()


def _bucket() -> str:
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")
    return config.S3_BUCKET


def _day_datetime(operating_day: str) -> datetime:
    return datetime.fromisoformat(operating_day).replace(tzinfo=timezone.utc)


def _manifest_key(resource: IstdatenResource) -> str:
    data_key = build_key(
        SOURCE,
        "csv",
        now=_day_datetime(resource.operating_day),
        run_id=resource.run_id,
    )
    return data_key.rsplit("/", 1)[0] + "/manifest.json"


def loaded_versions() -> dict[str, set[str]]:
    """
    Read which file versions are already stored

    Returns:
        dict[str, set[str]]: operating day -> fingerprints with a manifest
    """
    client = boto3.client("s3")
    versions: dict[str, set[str]] = {}
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=_bucket(), Prefix=f"raw/{SOURCE}/dt="
    ):
        for obj in page.get("Contents", []):
            match = _MANIFEST_KEY.match(obj["Key"])
            if match:
                versions.setdefault(match.group(1), set()).add(match.group(2))
    return versions


def plan_sync(
    since: str | None = None,
    max_days: int | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """
    Compare the catalogue with S3 and list the days that need loading

    Args:
        since: Ignore operating days before this date (YYYY-MM-DD)
        max_days: Load at most this many days, newest first
        today: Reference date for the freshness check, defaults to UTC today

    Returns:
        dict[str, Any]: ``operating_days`` (newest first), ``replaced`` (days
        whose file changed since the last load), ``latest_available`` and
        ``stale`` (newest published file older than ISTDATEN_V2_MAX_AGE_DAYS)
    """
    if since is not None:
        date.fromisoformat(since)
    if max_days is not None and max_days < 1:
        raise ValueError("max_days must be >= 1")
    resources = list_istdaten_resources()
    loaded = loaded_versions()

    pending: list[str] = []
    replaced: list[str] = []
    for resource in resources:
        if since is not None and resource.operating_day < since:
            continue
        versions = loaded.get(resource.operating_day, set())
        if resource.fingerprint in versions:
            continue
        pending.append(resource.operating_day)
        if versions:
            replaced.append(resource.operating_day)
    pending.sort(reverse=True)
    if max_days is not None:
        pending = pending[:max_days]

    today = today or datetime.now(timezone.utc).date()
    latest = resources[-1].operating_day if resources else None
    stale = latest is None or (
        today - date.fromisoformat(latest)
        > timedelta(days=config.ISTDATEN_V2_MAX_AGE_DAYS)
    )
    replaced = sorted(set(replaced) & set(pending), reverse=True)
    plan = {
        "source": SOURCE,
        "operating_days": pending,
        "replaced": replaced,
        "available": len(resources),
        "latest_available": latest,
        "stale": stale,
    }
    logger.info(
        "Ist-Daten v2 sync plan: %d to load (%d replaced), latest %s, stale=%s",
        len(pending),
        len(replaced),
        latest,
        stale,
    )
    return plan


def _manifest_exists(key: str) -> bool:
    try:
        boto3.client("s3").head_object(Bucket=_bucket(), Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
            return False
        raise
    return True


def load_operating_day(operating_day: str) -> dict[str, Any]:
    """
    Stream one daily file unchanged to S3 and write its manifest

    Loading is idempotent: if the current file version already has a manifest,
    nothing is downloaded. A size mismatch with the catalogue raises and leaves
    no manifest, so the next sync retries the day.

    Args:
        operating_day: Operating day (YYYY-MM-DD) as listed in the catalogue

    Returns:
        dict[str, Any]: Status, run ID and S3 URI of the data file
    """
    resource = find_resource(operating_day)
    bucket = _bucket()
    day_dt = _day_datetime(operating_day)
    data_key = build_key(SOURCE, "csv", now=day_dt, run_id=resource.run_id)
    uri = f"s3://{bucket}/{data_key}"
    if _manifest_exists(_manifest_key(resource)):
        logger.info("Ist-Daten v2 %s already loaded as %s", operating_day, uri)
        return {
            "status": "skipped",
            "operating_day": operating_day,
            "run_id": resource.run_id,
            "uri": uri,
        }

    response = open_resource_stream(resource)
    try:
        stream = _MeteredStream(cast(BinaryIO, response.raw))
        boto3.client("s3").upload_fileobj(
            cast(Any, stream),
            bucket,
            data_key,
            ExtraArgs={"ContentType": "text/csv"},
        )
    finally:
        response.close()

    if resource.size is not None and stream.bytes_read != resource.size:
        raise RuntimeError(
            f"Ist-Daten v2 {operating_day}: wrote {stream.bytes_read} bytes, "
            f"catalogue lists {resource.size}"
        )
    write_run_manifest(
        SOURCE,
        resource.run_id,
        {
            "status": "completed",
            "operating_day": operating_day,
            "data_key": data_key,
            "bytes": stream.bytes_read,
            "md5": stream.md5,
            "header": stream.header,
            "ckan": {
                "resource_id": resource.resource_id,
                "url": resource.url,
                "hash": resource.hash,
                "size": resource.size,
                "created": resource.created,
                "last_modified": resource.last_modified,
                "md5_matches_hash": stream.md5 == resource.hash.lower(),
            },
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        },
        now=day_dt,
    )
    logger.info(
        "Loaded Ist-Daten v2 %s: %d bytes -> %s",
        operating_day,
        stream.bytes_read,
        uri,
    )
    return {
        "status": "completed",
        "operating_day": operating_day,
        "run_id": resource.run_id,
        "uri": uri,
        "bytes": stream.bytes_read,
    }


def load_latest() -> dict[str, Any]:
    """Load the newest published day (used by direct and local invocations)."""
    resources = list_istdaten_resources()
    if not resources:
        raise LookupError("The CKAN catalogue lists no Ist-Daten v2 files")
    return load_operating_day(resources[-1].operating_day)
