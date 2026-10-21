"""Fetch Transport data from Swiss public transport API"""

import logging

import requests

from src.config import config
from src.http import get_session

logger = logging.getLogger(__name__)


def fetch_locations(query: str = "Basel") -> dict:
    """
    Fetch transport data by location

    Args:
        query: Location name to search for

    Returns:
        dict: API response
    """
    try:
        response = get_session().get(
            f"{config.TRANSPORT_API_ENDPOINT}/locations",
            params={"query": query},
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("%s", e)
        raise
    return response.json()
