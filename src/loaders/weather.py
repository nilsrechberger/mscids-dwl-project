"""Fetch historical weather data from Open-Meteo"""

import logging

import requests

from src.config import config

logger = logging.getLogger(__name__)


def fetch_weather() -> dict:
    """
    Fetch hourly temperature data from the Open-Meteo archive API

    Args:
        None

    Returns:
        dict: API response
    """
    params: dict[str, str | float] = {
        "latitude": 47.0002,
        "longitude": 8.0143,
        "start_date": "2026-09-14",
        "end_date": "2026-09-28",
        "hourly": "temperature_2m",
    }
    try:
        response = requests.get(
            str(config.WEATHER_API_ENDPOINT), params=params, timeout=10
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("%s", e)
        raise
    return response.json()
