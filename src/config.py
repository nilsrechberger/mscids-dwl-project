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
    ISTDATEN_V2_CKAN_ENDPOINT = os.getenv(
        "ISTDATEN_V2_CKAN_ENDPOINT", "https://api.opentransportdata.swiss/ckan-api"
    )
    ISTDATEN_V2_DATASET_ID = os.getenv("ISTDATEN_V2_DATASET_ID", "ist-daten-v2")
    # Local runs: the key itself. Lambda: only the Secrets Manager secret ID/ARN.
    CKAN_API_KEY = os.getenv("CKAN_API_KEY")
    CKAN_API_KEY_SECRET_ID = os.getenv("CKAN_API_KEY_SECRET_ID")
    # A sync run fails when the newest published file is older than this
    ISTDATEN_V2_MAX_AGE_DAYS = int(os.getenv("ISTDATEN_V2_MAX_AGE_DAYS", "2"))
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
