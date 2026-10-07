"""Fetch Transport data from Swiss public transport API"""

import logging

logger = logging.getLogger(__name__)

import requests

from src.config import config


def fetch_locations(query: str = "Basel") -> dict:
    """
    Fetch transport data by location

    Args:
        location: Specifies the location name to search for

    Returns:
        dict: API response
    """
    try:
        response = requests.get(
            f"{config.TRANSPORT_API_ENDPOINT}/locations",
            params={"query": query},
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
            print(e)
    return response.json()
