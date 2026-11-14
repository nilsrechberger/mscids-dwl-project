"""Fetch Transport data from Swiss public transport API"""

import logging
from collections.abc import Iterable

import requests

from src.config import config
from src.http import get_session

logger = logging.getLogger(__name__)


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
    except requests.exceptions.RequestException as e:
        logger.error("%s", e)
        raise
    return response.json()


def fetch_all_locations(municipalities: Iterable[str]) -> dict[str, dict]:
    """
    Fetch transport locations for every given municipality

    A failing municipality is logged and skipped, so one bad request does not
    abort the whole run. If every request fails the error is raised.

    Args:
        municipalities: Municipality names to search for

    Returns:
        dict[str, dict]: Municipality name -> API response
    """
    session = get_session()
    results: dict[str, dict] = {}
    failed: list[str] = []
    last_error: requests.exceptions.RequestException | None = None
    for name in municipalities:
        try:
            results[name] = fetch_locations(name, session=session)
        except requests.exceptions.RequestException as e:
            failed.append(name)
            last_error = e
    if failed:
        logger.warning("%d municipalities failed: %s", len(failed), failed[:20])
        if not results and last_error:
            raise last_error
    logger.info("Fetched locations for %d municipalities", len(results))
    return results
