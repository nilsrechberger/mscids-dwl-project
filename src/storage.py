"""Writes raw loader output to S3"""

from datetime import datetime, timezone

import boto3

from src.config import config


def build_key(
    source: str,
    extension: str,
    now: datetime | None = None,
    part: int | None = None,
) -> str:
    """
    Build the S3 object key for a raw file

    Args:
        source: Name of the data source, e.g. "weather"
        extension: File extension without dot, e.g. "json"
        now: Timestamp of the load, defaults to the current UTC time
        part: Batch number, appended to the file name so batches never collide

    Returns:
        str: Key like raw/weather/dt=2026-10-02/101530.json, or
            raw/transport/dt=2026-10-02/101530_part0003.json for a batch
    """
    now = now or datetime.now(timezone.utc)
    suffix = f"_part{part:04d}" if part is not None else ""
    return f"raw/{source}/dt={now:%Y-%m-%d}/{now:%H%M%S}{suffix}.{extension}"


def write_raw(source: str, data: bytes, extension: str, part: int | None = None) -> str:
    """
    Write raw bytes to the data lake bucket

    Args:
        source: Name of the data source, e.g. "weather"
        data: File content
        extension: File extension without dot, e.g. "json"
        part: Batch number for sources loaded in several invocations

    Returns:
        str: S3 URI of the written object
    """
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")

    key = build_key(source, extension, part=part)
    boto3.client("s3").put_object(Bucket=config.S3_BUCKET, Key=key, Body=data)
    return f"s3://{config.S3_BUCKET}/{key}"


def read_latest_raw(source: str) -> bytes | None:
    """
    Read the newest raw file of a source from the data lake bucket

    Keys are partitioned by date and time, so the lexicographically largest
    key is the newest one.

    Args:
        source: Name of the data source, e.g. "municipality"

    Returns:
        bytes | None: File content, or None if the source has no files yet
    """
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")

    client = boto3.client("s3")
    keys = [
        obj["Key"]
        for page in client.get_paginator("list_objects_v2").paginate(
            Bucket=config.S3_BUCKET, Prefix=f"raw/{source}/"
        )
        for obj in page.get("Contents", [])
    ]
    if not keys:
        return None
    body = client.get_object(Bucket=config.S3_BUCKET, Key=max(keys))["Body"]
    return body.read()
