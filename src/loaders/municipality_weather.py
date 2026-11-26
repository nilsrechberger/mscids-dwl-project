"""Fetch raw Open-Meteo responses for municipality weather batches."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlencode

import boto3
import requests

from src.config import config
from src.http import get_session

HOURLY_VARIABLES = (
    "temperature_2m",
    "precipitation",
    "rain",
    "snowfall",
    "wind_speed_10m",
    "weather_code",
)


def load_weather_points(path: str | Path) -> list[dict[str, str]]:
    """Load a versioned municipality weather-point CSV."""
    if not path:
        raise RuntimeError("MUNICIPALITY_WEATHER_POINTS is not set")
    path_value = str(path)
    handle: TextIO
    if path_value.startswith("s3://"):
        bucket, _, key = path_value[5:].partition("/")
        if not bucket or not key:
            raise ValueError("S3 weather-point snapshot must be s3://bucket/key")
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        handle = io.StringIO(body.decode("utf-8-sig"), newline="")
    else:
        handle = Path(path).open("r", encoding="utf-8-sig", newline="")
    with handle:
        points = list(csv.DictReader(handle))
    required = {"gdenr", "gdename", "latitude", "longitude"}
    missing = required.difference(points[0] if points else set())
    if missing:
        raise ValueError(f"Weather points are missing columns: {sorted(missing)}")
    if not points:
        raise ValueError("Weather points file is empty")
    return points


def build_url(points: list[dict[str, str]], start_date: str, end_date: str) -> str:
    """Build one multi-location Open-Meteo archive request."""
    params = {
        "latitude": ",".join(point["latitude"] for point in points),
        "longitude": ",".join(point["longitude"] for point in points),
        "hourly": ",".join(HOURLY_VARIABLES),
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "Europe/Berlin",
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
        "wind_speed_unit": "kmh",
    }
    return f"{config.MUNICIPALITY_WEATHER_API_ENDPOINT}?{urlencode(params)}"


def fetch_batch(
    points: list[dict[str, str]], start_date: str, end_date: str
) -> dict[str, Any]:
    """Fetch one batch and preserve request metadata with the raw response."""
    if not config.MUNICIPALITY_WEATHER_API_ENDPOINT:
        raise RuntimeError("MUNICIPALITY_WEATHER_API_ENDPOINT is not set")
    if not points:
        raise ValueError("Cannot fetch an empty municipality weather batch")
    # month-long backfill requests take longer than single days
    response = get_session().get(
        build_url(points, start_date, end_date), timeout=(10, 180)
    )
    response.raise_for_status()
    payload: Any = response.json()
    responses = payload if isinstance(payload, list) else [payload]
    if len(responses) != len(points):
        raise ValueError(
            f"Expected {len(points)} weather responses, got {len(responses)}"
        )
    return {
        "request": {
            "start_date": start_date,
            "end_date": end_date,
            "hourly": list(HOURLY_VARIABLES),
            "points": points,
        },
        "response": payload,
    }
