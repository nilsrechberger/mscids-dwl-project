"""Entry point: fetch one source and write the raw data to S3

Local / container: python -m src.run weather
Lambda handler:    src.run.handler  (event: {"source": "weather"})

Transport is loaded in batches of municipalities so a single invocation stays
below the Lambda timeout. Event: {"source": "transport", "batch": 0}. The
response contains "next_batch" until the last batch is done (null afterwards),
so a Step Functions loop or a script can walk through all batches. Locally,
`python -m src.run transport` runs all batches in sequence.
"""

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.config import config
from src.loaders.gtfs_rt import fetch_gtfs_rt
from src.loaders.municipality import fetch_municipality, parse_municipality_names
from src.loaders.municipality_weather import fetch_batch, load_weather_points
from src.loaders.transport import fetch_all_locations_with_status
from src.loaders.weather import fetch_weather
from src.log import setup_logging
from src.sources import ALL_SOURCES, require_source
from src.istdaten_sync import (
    load_archive_day,
    load_latest,
    load_operating_day,
    plan_archive_import,
    plan_sync,
)
from src.storage import read_latest_raw, write_raw, write_run_manifest
from src.runs import finalize_run, validate_run_context

logger = logging.getLogger(__name__)


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data).encode("utf-8")


@dataclass
class BatchResult:
    """Outcome of one batch invocation"""

    uri: str
    next_batch: int | None
    failed_municipalities: tuple[str, ...] = ()


def _run_datetime(observation_date: str | None) -> datetime | None:
    """Midnight UTC of the observation date, used for the dt= partition."""
    if not observation_date:
        return None
    return datetime.fromisoformat(observation_date).replace(tzinfo=timezone.utc)


def _municipality_names() -> list[str]:
    """
    Municipality names from the newest raw file in the data lake

    The list rarely changes, so it is read from the file the municipality
    loader already stored instead of being downloaded for every batch. Only
    if no file exists yet, it is downloaded from the BFS.
    """
    content = read_latest_raw("municipality")
    if content is None:
        logger.info("No municipality file in the data lake, downloading it")
        content = fetch_municipality().content
    return parse_municipality_names(content)


def _fetch_transport_batch(
    batch: int, batch_size: int, observation_date: str | None = None
) -> tuple[dict, int, tuple[str, ...]]:
    """
    Fetch one slice of the municipality list

    The legacy transport API has no historical mode, so observation_date is
    accepted for a uniform signature and ignored.
    """
    names = _municipality_names()
    total = -(-len(names) // batch_size)
    start = batch * batch_size
    result = fetch_all_locations_with_status(names[start : start + batch_size])
    return result.results, total, result.failed


def _fetch_municipality_weather_batch(
    batch: int, batch_size: int, observation_date: str | None = None
) -> tuple[dict, int, tuple[str, ...]]:
    """Fetch one raw Open-Meteo batch for the configured point snapshot."""
    points = load_weather_points(config.MUNICIPALITY_WEATHER_POINTS or "")
    start_date = observation_date or config.MUNICIPALITY_WEATHER_START_DATE
    end_date = observation_date or config.MUNICIPALITY_WEATHER_END_DATE
    if not start_date or not end_date:
        raise RuntimeError("MUNICIPALITY_WEATHER_START_DATE and _END_DATE must be set")
    total = -(-len(points) // batch_size)
    start = batch * batch_size
    payload = fetch_batch(
        points[start : start + batch_size],
        start_date,
        end_date,
    )
    return payload, total, ()


# source name -> function returning (file content, file extension)
LOADERS: dict[str, Callable[[], tuple[bytes, str]]] = {
    "weather": lambda: (_json_bytes(fetch_weather()), "json"),
    "gtfs_rt": lambda: (_json_bytes(fetch_gtfs_rt()), "json"),
    "municipality": lambda: (fetch_municipality().content, "xlsx"),
}


# sources loaded in several invocations:
# name -> function(batch, batch_size, observation_date) returning
# (payload, total batches, failed items)
BatchFetcher = Callable[[int, int, str | None], tuple[dict, int, tuple[str, ...]]]
BATCHED_LOADERS: dict[str, BatchFetcher] = {
    "transport": _fetch_transport_batch,
    "municipality_weather": _fetch_municipality_weather_batch,
}


def default_batch_size(source: str) -> int:
    """Configured items per invocation for a batched source."""
    if source == "municipality_weather":
        return config.MUNICIPALITY_WEATHER_BATCH_SIZE
    return config.TRANSPORT_BATCH_SIZE


def run_batch(
    source: str,
    batch: int = 0,
    batch_size: int | None = None,
    run_id: str | None = None,
    observation_date: str | None = None,
) -> BatchResult:
    """
    Fetch one batch of a batched source and write it to S3

    Args:
        source: Name of the loader, one of BATCHED_LOADERS
        batch: Zero-based batch number
        batch_size: Items per batch, defaults to default_batch_size(source)
        run_id: Deterministic run ID; enables batch and final manifests
        observation_date: Day to load (YYYY-MM-DD), also used for dt=

    Returns:
        BatchResult: S3 URI and the next batch number (None after the last)
    """
    if source not in BATCHED_LOADERS:
        raise ValueError(f"'{source}' is not a batched source")
    size = batch_size or default_batch_size(source)
    if batch < 0 or size < 1:
        raise ValueError("batch must be >= 0 and batch_size >= 1")

    data, total, failed = BATCHED_LOADERS[source](batch, size, observation_date)
    if batch >= total:
        raise ValueError(f"Batch {batch} out of range, {source} has {total} batches")
    payload = _json_bytes(data)
    run_datetime = _run_datetime(observation_date)
    if run_id is None:
        uri = write_raw(source, payload, "json", part=batch)
    else:
        uri = write_raw(
            source,
            payload,
            "json",
            part=batch,
            run_id=run_id,
            now=run_datetime,
        )
    logger.info(
        "Loaded %s batch %d/%d: %d bytes -> %s",
        source,
        batch + 1,
        total,
        len(payload),
        uri,
    )
    if run_id is not None:
        request = data.get("request") if isinstance(data, dict) else None
        items = request.get("points") if isinstance(request, dict) else None
        metadata = {
            "batch": batch,
            "batch_count": total,
            "completed_batches": batch + 1,
            "failed_batches": [batch] if failed else [],
            "failed_municipalities": list(failed),
            "items_in_batch": len(items) if isinstance(items, list) else len(data),
            "status": "partial" if failed else "completed",
        }
        write_run_manifest(source, run_id, metadata, now=run_datetime, part=batch)
        if batch + 1 == total:
            write_run_manifest(
                source,
                run_id,
                {
                    **metadata,
                    "status": "completed_with_failures" if failed else "completed",
                },
                now=run_datetime,
            )
    return BatchResult(
        uri,
        batch + 1 if batch + 1 < total else None,
        failed_municipalities=failed,
    )


def run(
    source: str, run_id: str | None = None, observation_date: str | None = None
) -> str:
    """
    Fetch one source and write the raw result to S3

    Args:
        source: Name of the loader, one of LOADERS

    Returns:
        str: S3 URI of the written object
    """
    require_source(source)
    if source in BATCHED_LOADERS:
        # all batches in sequence, for local runs
        result = run_batch(source, run_id=run_id, observation_date=observation_date)
        while result.next_batch is not None:
            result = run_batch(
                source,
                result.next_batch,
                run_id=run_id,
                observation_date=observation_date,
            )
        return result.uri
    if source == "istdaten_v2":
        # newest published day; history is loaded via the sync state machine
        return str(load_latest()["uri"])
    data, extension = LOADERS[source]()
    if run_id is None:
        uri = write_raw(source, data, extension)
    else:
        uri = write_raw(
            source,
            data,
            extension,
            run_id=run_id,
            now=_run_datetime(observation_date),
        )
    logger.info("Loaded %s: %d bytes -> %s", source, len(data), uri)
    return uri


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler

    Event: {"source": "<loader name>"}. Batched sources also accept
    "batch" (default 0) and "batch_size", and return "next_batch".
    The orchestration state machine uses ``action=finalize`` after the last
    batch to aggregate deterministic S3 manifests.

    Ist-Daten v2: ``action=plan_istdaten_sync`` (optional ``input`` with
    ``since``/``max_days``) returns the operating days to load;
    ``{"source": "istdaten_v2", "operating_day": "YYYY-MM-DD"}`` loads one
    day; without ``operating_day`` the newest published day is loaded.
    ``action=plan_istdaten_archive`` (``input`` with ``since``, ``until`` and
    optional ``max_days``) lists archive days that are not loaded yet; adding
    ``"archive_month": "YYYY-MM"`` to the load event reads the day from the
    monthly ZIP archive instead of CKAN.
    """
    logging.getLogger().setLevel(logging.INFO)
    if event.get("action") == "plan_istdaten_sync":
        options = event.get("input") or {}
        if not isinstance(options, dict):
            raise ValueError("plan_istdaten_sync 'input' must be an object")
        max_days = options.get("max_days")
        return plan_sync(
            since=options.get("since"),
            max_days=int(max_days) if max_days is not None else None,
        )
    if event.get("action") == "plan_istdaten_archive":
        archive_options = event.get("input") or {}
        if not isinstance(archive_options, dict):
            raise ValueError("plan_istdaten_archive 'input' must be an object")
        since, until = archive_options.get("since"), archive_options.get("until")
        if not isinstance(since, str) or not isinstance(until, str):
            raise ValueError("plan_istdaten_archive needs 'since' and 'until'")
        archive_max_days = archive_options.get("max_days")
        return plan_archive_import(
            since,
            until,
            int(archive_max_days) if archive_max_days is not None else None,
        )
    if event.get("action") == "prepare_daily":
        source = event.get("source")
        point_snapshot = event.get("point_snapshot")
        execution_id = event.get("execution_id")
        execution_start_date = event.get("execution_start_date")
        if source != "municipality_weather":
            raise ValueError(
                "prepare_daily currently supports municipality_weather only"
            )
        if not all(
            isinstance(value, str) and value
            for value in (
                point_snapshot,
                execution_id,
                execution_start_date,
            )
        ):
            raise ValueError(
                "prepare_daily requires point_snapshot, execution_id and "
                "execution_start_date"
            )
        assert isinstance(point_snapshot, str)
        assert isinstance(execution_id, str)
        assert isinstance(execution_start_date, str)
        observation_date = (
            date.fromisoformat(execution_start_date) - timedelta(days=1)
        ).isoformat()
        return {
            "source": source,
            "run_id": f"municipality-weather-{observation_date}-{point_snapshot}",
            "execution_id": execution_id,
            "observation_date": observation_date,
            "point_snapshot": point_snapshot,
            "batch": int(event.get("batch", 0)),
            "batch_size": int(
                event.get("batch_size", config.MUNICIPALITY_WEATHER_BATCH_SIZE)
            ),
        }
    if event.get("action") == "finalize":
        finalize_source = event.get("source")
        run_id = event.get("run_id")
        finalize_observation_date = event.get("observation_date")
        if not all(
            isinstance(value, str) and value
            for value in (finalize_source, run_id, finalize_observation_date)
        ):
            raise ValueError(
                "finalize event requires source, run_id and observation_date"
            )
        assert isinstance(finalize_source, str)
        assert isinstance(run_id, str)
        assert isinstance(finalize_observation_date, str)
        require_source(finalize_source)
        validate_run_context(
            {
                **event,
                "execution_id": event.get("execution_id", "step-functions"),
            },
            finalize_source,
        )
        return finalize_run(
            finalize_source,
            run_id,
            finalize_observation_date,
            metadata={
                key: event[key]
                for key in ("execution_id", "point_snapshot")
                if event.get(key) is not None
            },
        )
    source = event.get("source")
    if not isinstance(source, str):
        raise ValueError(
            f"Event must contain a string 'source'; choose from {ALL_SOURCES}"
        )
    require_source(source)
    if source == "istdaten_v2":
        operating_day = event.get("operating_day")
        if operating_day is None:
            return load_latest()
        if not isinstance(operating_day, str):
            raise ValueError("operating_day must be a YYYY-MM-DD string")
        date.fromisoformat(operating_day)
        archive_month = event.get("archive_month")
        if archive_month is not None:
            if not isinstance(archive_month, str):
                raise ValueError("archive_month must be a YYYY-MM string")
            return load_archive_day(operating_day, archive_month)
        return load_operating_day(operating_day)
    validate_run_context(event, source)
    if source in BATCHED_LOADERS:
        if event.get("run_id") is None:
            result = run_batch(
                source, int(event.get("batch", 0)), event.get("batch_size")
            )
        else:
            result = run_batch(
                source,
                int(event.get("batch", 0)),
                event.get("batch_size"),
                event["run_id"],
                event.get("observation_date"),
            )
        return {
            "uri": result.uri,
            "next_batch": result.next_batch,
            "failed_municipalities": list(result.failed_municipalities),
        }
    if event.get("run_id") is None:
        return {"uri": run(source)}
    return {
        "uri": run(
            source,
            event["run_id"],
            event.get("observation_date"),
        )
    }


if __name__ == "__main__":
    setup_logging()
    if len(sys.argv) != 2:
        sys.exit(f"Usage: python -m src.run <{'|'.join(ALL_SOURCES)}>")
    run(sys.argv[1])
