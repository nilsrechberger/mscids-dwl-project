"""Writes raw loader output to S3"""

from datetime import datetime, timezone
import json
import re
from typing import Any, BinaryIO

import boto3

from src.config import config

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _validate_run_id(run_id: str) -> None:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(
            "run_id must contain 1-64 letters, numbers, dots, underscores or hyphens"
        )


def build_key(
    source: str,
    extension: str,
    now: datetime | None = None,
    part: int | None = None,
    run_id: str | None = None,
) -> str:
    """Build a backward-compatible or deterministic raw S3 object key."""
    now = now or datetime.now(timezone.utc)
    if run_id is None:
        suffix = f"_part{part:04d}" if part is not None else ""
        filename = f"{now:%H%M%S}{suffix}.{extension}"
        return f"raw/{source}/dt={now:%Y-%m-%d}/{filename}"

    _validate_run_id(run_id)
    filename = (
        f"part{part:04d}.{extension}" if part is not None else f"data.{extension}"
    )
    return f"raw/{source}/dt={now:%Y-%m-%d}/run={run_id}/{filename}"


def write_raw(
    source: str,
    data: bytes,
    extension: str,
    part: int | None = None,
    run_id: str | None = None,
    now: datetime | None = None,
) -> str:
    """Write raw bytes to S3, optionally under a deterministic run prefix."""
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")

    key = build_key(source, extension, now=now, part=part, run_id=run_id)
    boto3.client("s3").put_object(Bucket=config.S3_BUCKET, Key=key, Body=data)
    return f"s3://{config.S3_BUCKET}/{key}"


def write_raw_stream(
    source: str,
    stream: BinaryIO,
    extension: str,
    part: int | None = None,
    run_id: str | None = None,
    now: datetime | None = None,
) -> str:
    """Upload a raw stream without materializing it in Lambda memory."""
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")

    key = build_key(source, extension, now=now, part=part, run_id=run_id)
    boto3.client("s3").upload_fileobj(stream, config.S3_BUCKET, key)
    return f"s3://{config.S3_BUCKET}/{key}"


def write_run_manifest(
    source: str,
    run_id: str,
    metadata: dict[str, Any],
    now: datetime | None = None,
    part: int | None = None,
) -> str:
    """Write deterministic metadata for one run or one completed batch."""
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")
    key = build_key(source, "json", now=now, run_id=run_id)
    manifest_name = "manifest.json" if part is None else f"manifest_part{part:04d}.json"
    key = key.rsplit("/", 1)[0] + f"/{manifest_name}"
    body = json.dumps(
        {"source": source, "run_id": run_id, **metadata},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    boto3.client("s3").put_object(
        Bucket=config.S3_BUCKET,
        Key=key,
        Body=body,
        ContentType="application/json",
    )
    return f"s3://{config.S3_BUCKET}/{key}"


def read_latest_raw(source: str) -> bytes | None:
    """Read the newest raw file of a source from the data lake bucket."""
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")

    client = boto3.client("s3")
    keys = [
        obj["Key"]
        for page in client.get_paginator("list_objects_v2").paginate(
            Bucket=config.S3_BUCKET, Prefix=f"raw/{source}/"
        )
        for obj in page.get("Contents", [])
        if not obj["Key"].endswith("/manifest.json") and "/run=" not in obj["Key"]
    ]
    if not keys:
        return None
    body = client.get_object(Bucket=config.S3_BUCKET, Key=max(keys))["Body"]
    return body.read()
