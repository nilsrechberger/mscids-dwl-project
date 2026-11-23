"""Keep raw/istdaten_v2 in sync with the CKAN catalogue.

Every daily file is stored under its operating day and a run ID that encodes
the file version (the CKAN content hash):

    raw/istdaten_v2/dt=<operating day>/run=istdaten-v2-<day>-<hash12>/data.csv
    raw/istdaten_v2/dt=<operating day>/run=istdaten-v2-<day>-<hash12>/manifest.json

The manifest is written only after a complete upload, so its existence marks a
loaded version. Planning compares the catalogue against these manifests and
returns every day that is missing or whose file was replaced by the provider.

Days older than the CKAN window come from the monthly ZIP archives
(``plan_archive_import`` / ``load_archive_day``). They use the same layout; the
version marker is the CRC32 of the ZIP member instead of the CKAN hash, and a
day that already has any loaded version is skipped, so archive and CKAN files
never coexist for one day.
"""

import hashlib
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, BinaryIO, cast

import boto3
from botocore.exceptions import ClientError

from src.config import config
from src.loaders.istdaten_archive import (
    ArchiveNotFound,
    list_archive_members,
    open_archive,
    validate_month,
)
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


def _day_versions(operating_day: str) -> set[str]:
    """Fingerprints of all loaded versions of one operating day."""
    prefix = f"raw/{SOURCE}/dt={operating_day}/"
    response = boto3.client("s3").list_objects_v2(Bucket=_bucket(), Prefix=prefix)
    versions: set[str] = set()
    for obj in response.get("Contents", []):
        match = _MANIFEST_KEY.match(obj["Key"])
        if match:
            versions.add(match.group(2))
    return versions


def _archive_months(start: date, end: date) -> list[str]:
    months: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def plan_archive_import(
    since: str, until: str, max_days: int | None = None
) -> dict[str, Any]:
    """
    List the archive days in a date range that are not loaded yet

    Only the ZIP central directories are read. Months whose archive is not
    published (yet) are reported in ``missing_months``.

    Args:
        since: First operating day to import (YYYY-MM-DD)
        until: Last operating day to import (YYYY-MM-DD)
        max_days: Import at most this many days, oldest first

    Returns:
        dict[str, Any]: ``items`` (``operating_day`` and ``archive_month`` per
        day to load, oldest first), ``available``, ``already_loaded`` and
        ``missing_months``
    """
    start, end = date.fromisoformat(since), date.fromisoformat(until)
    if start > end:
        raise ValueError("since must not be after until")
    if max_days is not None and max_days < 1:
        raise ValueError("max_days must be >= 1")
    loaded = loaded_versions()

    items: list[dict[str, str]] = []
    missing_months: list[str] = []
    available = already_loaded = 0
    for month in _archive_months(start, end):
        try:
            members = list_archive_members(month)
        except ArchiveNotFound:
            missing_months.append(month)
            continue
        for member in members:
            if not since <= member.operating_day <= until:
                continue
            available += 1
            if loaded.get(member.operating_day):
                already_loaded += 1
                continue
            items.append(
                {"operating_day": member.operating_day, "archive_month": month}
            )
    items.sort(key=lambda item: item["operating_day"])
    if max_days is not None:
        items = items[:max_days]
    logger.info(
        "Ist-Daten v2 archive plan %s..%s: %d to load, %d already loaded, "
        "missing months %s",
        since,
        until,
        len(items),
        already_loaded,
        missing_months,
    )
    return {
        "source": SOURCE,
        "since": since,
        "until": until,
        "items": items,
        "available": available,
        "already_loaded": already_loaded,
        "missing_months": missing_months,
    }


def load_archive_day(
    operating_day: str, archive_month: str | None = None
) -> dict[str, Any]:
    """
    Stream one day from a monthly archive unchanged to S3 and write its manifest

    The ZIP member is decompressed while streaming; ``zipfile`` verifies its
    CRC32 at the end, so a corrupt member aborts the upload. Days that already
    have any loaded version (from CKAN or an earlier import) are skipped.

    Args:
        operating_day: Operating day (YYYY-MM-DD)
        archive_month: Archive month (YYYY-MM), defaults to the day's month

    Returns:
        dict[str, Any]: Status, run ID and S3 URI of the data file
    """
    date.fromisoformat(operating_day)
    month = validate_month(archive_month or operating_day[:7])
    existing = _day_versions(operating_day)
    if existing:
        logger.info(
            "Ist-Daten v2 %s already loaded (versions %s), skipping archive",
            operating_day,
            sorted(existing),
        )
        return {
            "status": "skipped",
            "operating_day": operating_day,
            "existing_versions": sorted(existing),
        }

    bucket = _bucket()
    day_dt = _day_datetime(operating_day)
    archive, members = open_archive(month)
    try:
        member = next(
            (item for item in members if item.operating_day == operating_day), None
        )
        if member is None:
            raise LookupError(f"Archive {month} contains no file for {operating_day}")
        data_key = build_key(SOURCE, "csv", now=day_dt, run_id=member.run_id)
        with archive.open(member.name) as source:
            stream = _MeteredStream(cast(BinaryIO, source))
            boto3.client("s3").upload_fileobj(
                cast(Any, stream),
                bucket,
                data_key,
                ExtraArgs={"ContentType": "text/csv"},
            )
    finally:
        archive.close()

    if stream.bytes_read != member.file_size:
        raise RuntimeError(
            f"Ist-Daten v2 archive {operating_day}: wrote {stream.bytes_read} "
            f"bytes, ZIP lists {member.file_size}"
        )
    write_run_manifest(
        SOURCE,
        member.run_id,
        {
            "status": "completed",
            "origin": "archive",
            "operating_day": operating_day,
            "data_key": data_key,
            "bytes": stream.bytes_read,
            "md5": stream.md5,
            "header": stream.header,
            "archive": {
                "url": member.url,
                "month": member.month,
                "member": member.name,
                "crc32": member.fingerprint,
                "compressed_size": member.compressed_size,
                "file_size": member.file_size,
            },
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        },
        now=day_dt,
    )
    uri = f"s3://{bucket}/{data_key}"
    logger.info(
        "Loaded Ist-Daten v2 %s from archive %s: %d bytes -> %s",
        operating_day,
        month,
        stream.bytes_read,
        uri,
    )
    return {
        "status": "completed",
        "operating_day": operating_day,
        "run_id": member.run_id,
        "uri": uri,
        "bytes": stream.bytes_read,
    }
