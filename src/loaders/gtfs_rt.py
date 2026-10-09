"""Fetch data from the GTFS-RT API"""

import logging

import requests

from src.config import config

logger = logging.getLogger(__name__)


def fetch_gtfs_rt() -> dict:
    """
    Fetch data from the GTFS-RT API

    Args:
        None

    Returns:
        dict: Request response
    """
    try:
        response = requests.get(
            url=f"{config.GTFS_RT_API_ENDPOINT}?format=JSON",
            headers={"Authorization": f"{config.GTFS_RT_API_TOKEN}"},
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("%s", e)
        raise

    return response.json()
