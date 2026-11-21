"""Run context validation and S3 manifest finalization."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import boto3

from src.config import config
from src.storage import RUN_ID_PATTERN, write_run_manifest


def validate_run_context(event: dict[str, Any], source: str) -> None:
    """Validate the extended run contract when a run ID is supplied."""
    run_id = event.get("run_id")
    if run_id is None:
        return
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must contain 1-64 safe identifier characters")
    for field in ("observation_date", "execution_id"):
        value = event.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"run event requires non-empty '{field}'")
    try:
        date.fromisoformat(event["observation_date"])
    except (TypeError, ValueError) as error:
        raise ValueError("observation_date must use YYYY-MM-DD") from error
    if source == "municipality_weather":
        snapshot = event.get("point_snapshot")
        if not isinstance(snapshot, str) or not snapshot:
            raise ValueError(
                "municipality_weather run event requires non-empty 'point_snapshot'"
            )


def _manifest_keys(source: str, observation_date: str, run_id: str) -> list[str]:
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")
    client = boto3.client("s3")
    prefix = f"raw/{source}/dt={observation_date}/run={run_id}/manifest_part"
    return sorted(
        obj["Key"]
        for page in client.get_paginator("list_objects_v2").paginate(
            Bucket=config.S3_BUCKET, Prefix=prefix
        )
        for obj in page.get("Contents", [])
        if obj["Key"].endswith(".json")
    )


def finalize_run(
    source: str,
    run_id: str,
    observation_date: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate batch manifests and write the deterministic final manifest."""
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")
    date.fromisoformat(observation_date)
    keys = _manifest_keys(source, observation_date, run_id)
    client = boto3.client("s3")
    manifests: list[dict[str, Any]] = []
    for key in keys:
        body = client.get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read()
        manifests.append(json.loads(body))

    batch_count = max(
        (int(item.get("batch_count", 0)) for item in manifests), default=0
    )
    completed_batches = sorted(
        {int(item["batch"]) for item in manifests if "batch" in item}
    )
    failed_batches = sorted(
        {int(item["batch"]) for item in manifests if item.get("failed_municipalities")}
    )
    if not manifests:
        status = "failed"
    elif len(completed_batches) < batch_count:
        status = "partial"
    elif failed_batches:
        status = "completed_with_failures"
    else:
        status = "completed"

    summary: dict[str, Any] = {
        **(metadata or {}),
        "source": source,
        "run_id": run_id,
        "observation_date": observation_date,
        "batch_count": batch_count,
        "completed_batches": len(completed_batches),
        "failed_batches": failed_batches,
        "api_requests": len(manifests),
        "status": status,
        "finalized_at": datetime.now(timezone.utc).isoformat(),
    }
    write_run_manifest(
        source,
        run_id,
        summary,
        now=datetime.fromisoformat(observation_date).replace(tzinfo=timezone.utc),
    )
    return summary


def require_completed_run(
    source: str, run_id: str, observation_date: str
) -> dict[str, Any]:
    """Read the final manifest and reject non-completed runs."""
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")
    date.fromisoformat(observation_date)
    key = f"raw/{source}/dt={observation_date}/run={run_id}/manifest.json"
    body = (
        boto3.client("s3").get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read()
    )
    manifest = json.loads(body)
    if manifest.get("status") != "completed":
        raise RuntimeError(
            f"Run {run_id} is not complete: status={manifest.get('status', '<missing>')}"
        )
    return manifest
