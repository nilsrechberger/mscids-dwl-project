"""Fetch data from the GTFS-RT API"""

import logging

logger = logging.getLogger(__name__)

import requests

from src.config import config


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
        print(e)

    return response.json()
