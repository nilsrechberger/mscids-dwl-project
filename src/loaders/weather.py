"""Fetch historical weather data from Open-Meteo"""

import logging

import requests

from src.config import config
from src.http import get_session

logger = logging.getLogger(__name__)

HOURLY_VARIABLES = "temperature_2m,rain"

# canton code -> (latitude, longitude) of the cantonal capital
CANTONS: dict[str, tuple[float, float]] = {
    "AG": (47.3925, 8.0444),  # Aarau
    "AI": (47.3314, 9.4090),  # Appenzell
    "AR": (47.3835, 9.2793),  # Herisau
    "BE": (46.9480, 7.4474),  # Bern
    "BL": (47.4814, 7.7344),  # Liestal
    "BS": (47.5596, 7.5886),  # Basel
    "FR": (46.8065, 7.1620),  # Fribourg
    "GE": (46.2044, 6.1432),  # Geneve
    "GL": (47.0404, 9.0678),  # Glarus
    "GR": (46.8499, 9.5329),  # Chur
    "JU": (47.3667, 7.3444),  # Delemont
    "LU": (47.0502, 8.3093),  # Luzern
    "NE": (46.9900, 6.9293),  # Neuchatel
    "NW": (46.9580, 8.3660),  # Stans
    "OW": (46.8803, 8.2446),  # Sarnen
    "SG": (47.4245, 9.3767),  # St. Gallen
    "SH": (47.6959, 8.6349),  # Schaffhausen
    "SO": (47.2088, 7.5323),  # Solothurn
    "SZ": (47.0207, 8.6530),  # Schwyz
    "TG": (47.5536, 8.8987),  # Frauenfeld
    "TI": (46.1950, 9.0230),  # Bellinzona
    "UR": (46.8803, 8.6444),  # Altdorf
    "VD": (46.5197, 6.6323),  # Lausanne
    "VS": (46.2330, 7.3606),  # Sion
    "ZG": (47.1662, 8.5155),  # Zug
    "ZH": (47.3769, 8.5417),  # Zurich
}


def fetch_weather(
    start_date: str = "2026-09-14", end_date: str = "2026-09-28"
) -> dict[str, dict]:
    """
    Fetch hourly temperature and rain for all Swiss cantons from Open-Meteo

    All cantons are requested in a single call (Open-Meteo accepts comma
    separated coordinates and returns one result per location, in order).

    Args:
        start_date: First day to fetch (YYYY-MM-DD)
        end_date: Last day to fetch (YYYY-MM-DD)

    Returns:
        dict[str, dict]: Canton code -> Open-Meteo response for its capital
    """
    codes = list(CANTONS)
    params: dict[str, str] = {
        "latitude": ",".join(str(CANTONS[c][0]) for c in codes),
        "longitude": ",".join(str(CANTONS[c][1]) for c in codes),
        "start_date": start_date,
        "end_date": end_date,
        "hourly": HOURLY_VARIABLES,
    }
    try:
        response = get_session().get(
            str(config.WEATHER_API_ENDPOINT), params=params, timeout=30
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("%s", e)
        raise

    results = response.json()
    if len(results) != len(codes):
        raise ValueError(f"Expected {len(codes)} weather results, got {len(results)}")
    logger.info("Fetched weather for %d cantons", len(codes))
    return dict(zip(codes, results))
