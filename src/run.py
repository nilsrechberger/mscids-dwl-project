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
from datetime import datetime, timezone
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from src.config import config
from src.loaders.gtfs_rt import fetch_gtfs_rt
from src.loaders.istdaten_v2 import fetch_istdaten_v2
from src.loaders.municipality import fetch_municipality, parse_municipality_names
from src.loaders.municipality_weather import fetch_batch, load_weather_points
from src.loaders.transport import fetch_all_locations_with_status
from src.loaders.weather import fetch_weather
from src.log import setup_logging
from src.sources import ALL_SOURCES, require_source
from src.storage import (
    read_latest_raw,
    write_raw,
    write_raw_stream,
    write_run_manifest,
)
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
    batch: int, batch_size: int
) -> tuple[dict, int, tuple[str, ...]]:
    """Fetch one slice of the municipality list, returns (data, total batches)"""
    names = _municipality_names()
    total = -(-len(names) // batch_size)
    start = batch * batch_size
    result = fetch_all_locations_with_status(names[start : start + batch_size])
    return result.results, total, result.failed


def _fetch_municipality_weather_batch(
    batch: int, batch_size: int
) -> tuple[dict, int, tuple[str, ...]]:
    """Fetch one raw Open-Meteo batch for the configured point snapshot."""
    points = load_weather_points(config.MUNICIPALITY_WEATHER_POINTS or "")
    if (
        not config.MUNICIPALITY_WEATHER_START_DATE
        or not config.MUNICIPALITY_WEATHER_END_DATE
    ):
        raise RuntimeError("MUNICIPALITY_WEATHER_START_DATE and _END_DATE must be set")
    total = -(-len(points) // batch_size)
    start = batch * batch_size
    payload = fetch_batch(
        points[start : start + batch_size],
        config.MUNICIPALITY_WEATHER_START_DATE,
        config.MUNICIPALITY_WEATHER_END_DATE,
    )
    return payload, total, ()


# source name -> function returning (file content, file extension)
LOADERS: dict[str, Callable[[], tuple[bytes, str]]] = {
    "weather": lambda: (_json_bytes(fetch_weather()), "json"),
    "gtfs_rt": lambda: (_json_bytes(fetch_gtfs_rt()), "json"),
    "municipality": lambda: (fetch_municipality().content, "xlsx"),
}


# Large sources are streamed directly to S3 and never materialized in memory.
STREAM_LOADERS = {"istdaten_v2": fetch_istdaten_v2}


# sources loaded in several invocations: name -> function(batch, batch_size)
BATCHED_LOADERS: dict[str, Callable[[int, int], tuple[dict, int, tuple[str, ...]]]] = {
    "transport": _fetch_transport_batch,
    "municipality_weather": _fetch_municipality_weather_batch,
}


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
        batch_size: Items per batch, defaults to config.TRANSPORT_BATCH_SIZE

    Returns:
        BatchResult: S3 URI and the next batch number (None after the last)
    """
    if source not in BATCHED_LOADERS:
        raise ValueError(f"'{source}' is not a batched source")
    size = batch_size or config.TRANSPORT_BATCH_SIZE
    if batch < 0 or size < 1:
        raise ValueError("batch must be >= 0 and batch_size >= 1")

    data, total, failed = BATCHED_LOADERS[source](batch, size)
    if batch >= total:
        raise ValueError(f"Batch {batch} out of range, {source} has {total} batches")
    payload = _json_bytes(data)
    run_datetime = (
        datetime.fromisoformat(observation_date).replace(tzinfo=timezone.utc)
        if observation_date
        else None
    )
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
    if source in STREAM_LOADERS:
        response = STREAM_LOADERS[source]()
        try:
            run_datetime = (
                datetime.fromisoformat(observation_date).replace(tzinfo=timezone.utc)
                if observation_date
                else None
            )
            if run_id is None:
                uri = write_raw_stream(source, cast(Any, response.raw), "csv")
            else:
                uri = write_raw_stream(
                    source,
                    cast(Any, response.raw),
                    "csv",
                    run_id=run_id,
                    now=run_datetime,
                )
        finally:
            response.close()
        logger.info("Loaded %s as stream -> %s", source, uri)
        return uri
    data, extension = LOADERS[source]()
    if run_id is None:
        uri = write_raw(source, data, extension)
    else:
        run_datetime = (
            datetime.fromisoformat(observation_date).replace(tzinfo=timezone.utc)
            if observation_date
            else None
        )
        uri = write_raw(source, data, extension, run_id=run_id, now=run_datetime)
    logger.info("Loaded %s: %d bytes -> %s", source, len(data), uri)
    return uri


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler

    Event: {"source": "<loader name>"}. Batched sources also accept
    "batch" (default 0) and "batch_size", and return "next_batch".
    The orchestration state machine uses ``action=finalize`` after the last
    batch to aggregate deterministic S3 manifests.
    """
    logging.getLogger().setLevel(logging.INFO)
    if event.get("action") == "finalize":
        source = event.get("source")
        run_id = event.get("run_id")
        observation_date = event.get("observation_date")
        if not all(
            isinstance(value, str) and value
            for value in (source, run_id, observation_date)
        ):
            raise ValueError(
                "finalize event requires source, run_id and observation_date"
            )
        assert isinstance(source, str)
        assert isinstance(run_id, str)
        assert isinstance(observation_date, str)
        require_source(source)
        validate_run_context(
            {
                **event,
                "execution_id": event.get("execution_id", "step-functions"),
            },
            source,
        )
        return finalize_run(
            source,
            run_id,
            observation_date,
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
