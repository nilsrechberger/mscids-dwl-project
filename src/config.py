"""Project config module"""

import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Sets base config"""

    WEATHER_API_ENDPOINT = os.getenv("WEATHER_API_ENDPOINT")
    TRANSPORT_API_ENDPOINT = os.getenv("TRANSPORT_API_ENDPOINT")
    GTFS_RT_API_ENDPOINT = os.getenv("GTFS_RT_API_ENDPOINT")
    GTFS_RT_API_TOKEN = os.getenv("GTFS_RT_API_TOKEN")
    MUNICIPALITY_XLSX = os.getenv("MUNICIPALITY_XLSX")
    ISTDATEN_V2_ENDPOINT = os.getenv("ISTDATEN_V2_ENDPOINT")
    MUNICIPALITY_WEATHER_API_ENDPOINT = os.getenv(
        "MUNICIPALITY_WEATHER_API_ENDPOINT",
        "https://archive-api.open-meteo.com/v1/archive",
    )
    MUNICIPALITY_WEATHER_POINTS = os.getenv("MUNICIPALITY_WEATHER_POINTS")
    MUNICIPALITY_WEATHER_START_DATE = os.getenv("MUNICIPALITY_WEATHER_START_DATE")
    MUNICIPALITY_WEATHER_END_DATE = os.getenv("MUNICIPALITY_WEATHER_END_DATE")
    MUNICIPALITY_WEATHER_BATCH_SIZE = int(
        os.getenv("MUNICIPALITY_WEATHER_BATCH_SIZE", "50")
    )
    TRANSPORT_BATCH_SIZE = int(os.getenv("TRANSPORT_BATCH_SIZE", "300"))
    S3_BUCKET = os.getenv("S3_BUCKET")
    HTTP_MAX_RETRIES = int(os.getenv("HTTP_MAX_RETRIES", "3"))
    HTTP_BACKOFF_SECONDS = float(os.getenv("HTTP_BACKOFF_SECONDS", "1"))


config = Config()
