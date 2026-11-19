"""Fetch Transport data from Swiss public transport API"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass

import requests

from src.config import config
from src.http import get_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocationFetchResult:
    """Results and explicit failures from one municipality batch."""

    results: dict[str, dict]
    failed: tuple[str, ...]


def fetch_locations(
    query: str = "Basel", session: requests.Session | None = None
) -> dict:
    """
    Fetch transport data by location

    Args:
        query: Location name to search for
        session: Session to reuse across calls, a new one is created if omitted

    Returns:
        dict: API response
    """
    session = session or get_session()
    try:
        response = session.get(
            f"{config.TRANSPORT_API_ENDPOINT}/locations",
            params={"query": query},
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        logger.error("Transport request failed for %s: %s", query, error)
        raise
    return response.json()


def fetch_all_locations_with_status(
    municipalities: Iterable[str],
) -> LocationFetchResult:
    """Fetch a batch and return successful and failed municipality names."""
    session = get_session()
    results: dict[str, dict] = {}
    failed: list[str] = []
    for name in municipalities:
        try:
            results[name] = fetch_locations(name, session=session)
        except requests.exceptions.RequestException:
            failed.append(name)

    if failed:
        logger.warning(
            "Transport batch completed with %d failed municipalities: %s",
            len(failed),
            failed[:20],
        )
    logger.info(
        "Fetched locations for %d municipalities; failed=%d",
        len(results),
        len(failed),
    )
    if not results and failed:
        raise requests.exceptions.RequestException(
            f"All {len(failed)} municipality requests failed"
        )
    return LocationFetchResult(results=results, failed=tuple(failed))


def fetch_all_locations(municipalities: Iterable[str]) -> dict[str, dict]:
    """Backward-compatible wrapper returning only successful responses."""
    return fetch_all_locations_with_status(municipalities).results
