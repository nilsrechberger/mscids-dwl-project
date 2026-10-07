"""Fetch historical weather data from Open-Meteo"""

import openmeteo_requests

from openmeteo_sdk.WeatherApiResponse import WeatherApiResponse
import requests_cache
from retry_requests import retry


def fetch_weather(url: str) -> list[WeatherApiResponse]:
    """
    Fetch data from Open-Meteo data API

    Args:
        url: API Endpoint

    Returns:
        list: Weather API Responses
    """
    try:
        openmeteo = openmeteo_requests.Client()
        params = {
            "latitude": 47.0002,
            "longitude": 8.0143,
            "start_date": "2026-09-14",
            "end_date": "2026-09-28",
            "hourly": "temperature_2m",
        }
        responses = openmeteo.weather_api(url, params=params)
    except Exception as e:
            print(e)
    return responses
