"""Entry point: fetch one source and write the raw data to S3

Local / container: python -m src.run weather
Lambda handler:    src.run.handler  (event: {"source": "weather"})
"""

import json
import logging
import sys
from collections.abc import Callable
from typing import Any

from src.loaders.gtfs_rt import fetch_gtfs_rt
from src.loaders.municipality import fetch_municipality
from src.loaders.transport import fetch_locations
from src.loaders.weather import fetch_weather
from src.log import setup_logging
from src.storage import write_raw

logger = logging.getLogger(__name__)


def _json_bytes(data: Any) -> bytes:
    return json.dumps(data).encode("utf-8")


# source name -> function returning (file content, file extension)
LOADERS: dict[str, Callable[[], tuple[bytes, str]]] = {
    "weather": lambda: (_json_bytes(fetch_weather()), "json"),
    "transport": lambda: (_json_bytes(fetch_locations()), "json"),
    "gtfs_rt": lambda: (_json_bytes(fetch_gtfs_rt()), "json"),
    "municipality": lambda: (fetch_municipality().content, "xlsx"),
}


def run(source: str) -> str:
    """
    Fetch one source and write the raw result to S3

    Args:
        source: Name of the loader, one of LOADERS

    Returns:
        str: S3 URI of the written object
    """
    if source not in LOADERS:
        raise ValueError(f"Unknown source '{source}', choose from {sorted(LOADERS)}")

    data, extension = LOADERS[source]()
    uri = write_raw(source, data, extension)
    logger.info("Loaded %s: %d bytes -> %s", source, len(data), uri)
    return uri


def handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    """AWS Lambda handler, expects {"source": "<loader name>"}"""
    logging.getLogger().setLevel(logging.INFO)
    return {"uri": run(event["source"])}


if __name__ == "__main__":
    setup_logging()
    if len(sys.argv) != 2:
        sys.exit(f"Usage: python -m src.run <{'|'.join(sorted(LOADERS))}>")
    run(sys.argv[1])
