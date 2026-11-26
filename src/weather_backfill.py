"""Plan the historical municipality-weather backfill in monthly runs.

The daily weather run fetches one day for every point. Loading the history
day by day would cost one Open-Meteo call per point and day, far above the
free limit of 10,000 calls per day. Open-Meteo counts a request for one
location as one call per two weeks, so a whole month per request costs about
2.2 calls per point instead of 31. The backfill state machine therefore loads
one calendar month per run and waits between the months (default 24 hours),
which keeps every day below the limit together with the daily run.

Each month is a normal run of the ``municipality_weather`` source with an
``end_date``: raw batches and manifests are stored under
``raw/municipality_weather/dt=<first day of the month>/run=<run_id>/``. The
hourly timestamps inside each response identify the actual days.
"""

import json
import logging
from datetime import date, timedelta
from typing import Any

import boto3

from src.config import config
from src.storage import RUN_ID_PATTERN

logger = logging.getLogger(__name__)

SOURCE = "municipality_weather"
DEFAULT_INTERVAL_HOURS = 24


def month_ranges(since: date, until: date) -> list[tuple[date, date]]:
    """Split [since, until] into calendar months, clipped at both ends."""
    if since > until:
        raise ValueError("since must not be after until")
    ranges = []
    start = since
    while start <= until:
        next_month = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
        end = min(next_month - timedelta(days=1), until)
        ranges.append((start, end))
        start = end + timedelta(days=1)
    return ranges


def backfill_run_id(start: date, end: date, point_snapshot: str) -> str:
    """Deterministic run ID of one backfill month."""
    run_id = f"municipality-weather-{start}-{end}-{point_snapshot}"
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(f"point_snapshot gives an invalid run_id: {run_id}")
    return run_id


def _completed(run_id: str, start: date) -> bool:
    """True if the final manifest of this run exists with status completed."""
    if not config.S3_BUCKET:
        raise RuntimeError("S3_BUCKET is not set")
    key = f"raw/{SOURCE}/dt={start}/run={run_id}/manifest.json"
    client = boto3.client("s3")
    listing = client.list_objects_v2(Bucket=config.S3_BUCKET, Prefix=key, MaxKeys=1)
    if not any(obj["Key"] == key for obj in listing.get("Contents", [])):
        return False
    body = client.get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read()
    return json.loads(body).get("status") == "completed"


def plan_weather_backfill(options: dict[str, Any], execution_id: str) -> dict[str, Any]:
    """
    List the backfill months that still have to be loaded

    Args:
        options: Execution input with ``since`` and ``until`` (YYYY-MM-DD),
            ``point_snapshot`` and optional ``batch_size`` and
            ``interval_hours`` (wait between two months, default 24)
        execution_id: Step Functions execution name, kept in the manifests

    Returns:
        dict[str, Any]: ``items`` (one run event per month, oldest first, with
        ``wait_seconds`` before it) and ``already_loaded`` (skipped run IDs)
    """
    since, until = options.get("since"), options.get("until")
    point_snapshot = options.get("point_snapshot")
    if not isinstance(since, str) or not isinstance(until, str):
        raise ValueError("plan_weather_backfill needs 'since' and 'until'")
    if not isinstance(point_snapshot, str) or not point_snapshot:
        raise ValueError("plan_weather_backfill needs 'point_snapshot'")
    batch_size = int(options.get("batch_size", config.MUNICIPALITY_WEATHER_BATCH_SIZE))
    interval_hours = float(options.get("interval_hours", DEFAULT_INTERVAL_HOURS))
    if batch_size < 1 or interval_hours < 0:
        raise ValueError("batch_size must be >= 1 and interval_hours >= 0")
    if date.fromisoformat(until) >= date.today():
        raise ValueError("until must be in the past; the daily run loads yesterday")

    items: list[dict[str, Any]] = []
    already_loaded: list[str] = []
    for start, end in month_ranges(
        date.fromisoformat(since), date.fromisoformat(until)
    ):
        run_id = backfill_run_id(start, end, point_snapshot)
        if _completed(run_id, start):
            already_loaded.append(run_id)
            continue
        items.append(
            {
                "source": SOURCE,
                "run_id": run_id,
                "execution_id": execution_id,
                "observation_date": start.isoformat(),
                "end_date": end.isoformat(),
                "point_snapshot": point_snapshot,
                "batch": 0,
                "batch_size": batch_size,
                "wait_seconds": 0 if not items else int(interval_hours * 3600),
            }
        )
    logger.info(
        "Weather backfill %s..%s: %d months to load, %d already loaded",
        since,
        until,
        len(items),
        len(already_loaded),
    )
    return {"items": items, "already_loaded": already_loaded}
