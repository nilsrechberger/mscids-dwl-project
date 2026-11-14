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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.loaders.gtfs_rt import fetch_gtfs_rt
from src.config import config
from src.loaders.municipality import fetch_municipality, parse_municipality_names
from src.loaders.transport import fetch_all_locations
from src.loaders.weather import fetch_weather
from src.log import setup_logging
from src.storage import read_latest_raw, write_raw

logger = logging.getLogger(__name__)


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data).encode("utf-8")


@dataclass
class BatchResult:
    """Outcome of one batch invocation"""

    uri: str
    next_batch: int | None


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


def _fetch_transport_batch(batch: int, batch_size: int) -> tuple[dict, int]:
    """Fetch one slice of the municipality list, returns (data, total batches)"""
    names = _municipality_names()
    total = -(-len(names) // batch_size)
    start = batch * batch_size
    return fetch_all_locations(names[start : start + batch_size]), total


# source name -> function returning (file content, file extension)
LOADERS: dict[str, Callable[[], tuple[bytes, str]]] = {
    "weather": lambda: (_json_bytes(fetch_weather()), "json"),
    "gtfs_rt": lambda: (_json_bytes(fetch_gtfs_rt()), "json"),
    "municipality": lambda: (fetch_municipality().content, "xlsx"),
}


# sources loaded in several invocations: name -> function(batch, batch_size)
BATCHED_LOADERS: dict[str, Callable[[int, int], tuple[dict, int]]] = {
    "transport": _fetch_transport_batch,
}


def run_batch(
    source: str, batch: int = 0, batch_size: int | None = None
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

    data, total = BATCHED_LOADERS[source](batch, size)
    if batch >= total:
        raise ValueError(f"Batch {batch} out of range, {source} has {total} batches")
    payload = _json_bytes(data)
    uri = write_raw(source, payload, "json", part=batch)
    logger.info(
        "Loaded %s batch %d/%d: %d bytes -> %s",
        source,
        batch + 1,
        total,
        len(payload),
        uri,
    )
    return BatchResult(uri, batch + 1 if batch + 1 < total else None)


def run(source: str) -> str:
    """
    Fetch one source and write the raw result to S3

    Args:
        source: Name of the loader, one of LOADERS

    Returns:
        str: S3 URI of the written object
    """
    if source in BATCHED_LOADERS:
        # all batches in sequence, for local runs
        result = run_batch(source)
        while result.next_batch is not None:
            result = run_batch(source, result.next_batch)
        return result.uri
    if source not in LOADERS:
        raise ValueError(
            f"Unknown source '{source}', choose from {sorted([*LOADERS, *BATCHED_LOADERS])}"
        )

    data, extension = LOADERS[source]()
    uri = write_raw(source, data, extension)
    logger.info("Loaded %s: %d bytes -> %s", source, len(data), uri)
    return uri


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler

    Event: {"source": "<loader name>"}. Batched sources also accept
    "batch" (default 0) and "batch_size", and return "next_batch".
    """
    logging.getLogger().setLevel(logging.INFO)
    source = event["source"]
    if source in BATCHED_LOADERS:
        result = run_batch(source, int(event.get("batch", 0)), event.get("batch_size"))
        return {"uri": result.uri, "next_batch": result.next_batch}
    return {"uri": run(source)}


if __name__ == "__main__":
    setup_logging()
    if len(sys.argv) != 2:
        sys.exit(
            f"Usage: python -m src.run <{'|'.join(sorted([*LOADERS, *BATCHED_LOADERS]))}>"
        )
    run(sys.argv[1])
