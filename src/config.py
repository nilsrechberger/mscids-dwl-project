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
    S3_BUCKET = os.getenv("S3_BUCKET")


config = Config()
