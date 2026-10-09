"""Writes raw loader output to S3"""

from datetime import datetime, timezone

import boto3

from src.config import config


def build_key(source: str, extension: str, now: datetime | None = None) -> str:
    """
    Build the S3 object key for a raw file

    Args:
        source: Name of the data source, e.g. "weather"
        extension: File extension without dot, e.g. "json"
        now: Timestamp of the load, defaults to the current UTC time

    Returns:
        str: Key like raw/weather/dt=2026-10-02/101530.json
    """
    now = now or datetime.now(timezone.utc)
    return f"raw/{source}/dt={now:%Y-%m-%d}/{now:%H%M%S}.{extension}"


def write_raw(source: str, data: bytes, extension: str) -> str:
    """
    Write raw bytes to the data lake bucket

    Args:
        source: Name of the data source, e.g. "weather"
        data: File content
        extension: File extension without dot, e.g. "json"

    Returns:
        str: S3 URI of the written object
    """
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")

    key = build_key(source, extension)
    boto3.client("s3").put_object(Bucket=config.S3_BUCKET, Key=key, Body=data)
    return f"s3://{config.S3_BUCKET}/{key}"
