"""Downloads the municipality file from BFS"""

import logging

import requests

from src.config import config

logger = logging.getLogger(__name__)


def fetch_municipality() -> requests.Response:
    """
    Downloads the static XLSX file from the BFS

    Args:
        None

    Returns:
        requests.Response: Response containing the XLSX file
    """
    try:
        # The BFS endpoint serves the XLSX export on POST
        response = requests.post(
            f"{config.MUNICIPALITY_XLSX}",
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("%s", e)
        raise
    return response
