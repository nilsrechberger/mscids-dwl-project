#!/usr/bin/env python3
"""Fetch hourly Open-Meteo data for municipality representative points."""

from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HOURLY_VARIABLES = [
    "temperature_2m",
    "precipitation",
    "rain",
    "snowfall",
    "wind_speed_10m",
    "weather_code",
]


def build_url(
    base_url: str, points: list[dict[str, str]], start_date: str, end_date: str
) -> str:
    """Build one Open-Meteo request for a batch of locations."""
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
    return f"{base_url}?{urlencode(params)}"


def normalize_response(
    response: dict[str, Any] | list[dict[str, Any]], points: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Normalize one or multiple Open-Meteo response objects to long CSV rows."""
    responses = response if isinstance(response, list) else [response]
    rows: list[dict[str, str]] = []
    for point, payload in zip(points, responses):
        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        for index, timestamp in enumerate(times):
            row = {
                "gdenr": point["gdenr"],
                "gdename": point["gdename"],
                "latitude": point["latitude"],
                "longitude": point["longitude"],
                "time": timestamp,
            }
            for variable in HOURLY_VARIABLES:
                values = hourly.get(variable, [])
                row[variable] = (
                    ""
                    if index >= len(values) or values[index] is None
                    else str(values[index])
                )
            rows.append(row)
    return rows


def fetch_json(
    url: str, max_retries: int = 5, retry_base_seconds: float = 30.0
) -> dict[str, Any] | list[dict[str, Any]]:
    """Fetch one response and back off when Open-Meteo returns HTTP 429."""
    request = Request(url, headers={"User-Agent": "mscids-dwl-project-local-spike/1.0"})
    for attempt in range(max_retries + 1):
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code != 429 or attempt >= max_retries:
                raise
            retry_after = error.headers.get("Retry-After")
            try:
                wait_seconds = (
                    float(retry_after)
                    if retry_after
                    else retry_base_seconds * (2**attempt)
                )
            except ValueError:
                wait_seconds = retry_base_seconds * (2**attempt)
            time.sleep(wait_seconds)
    raise RuntimeError("unreachable retry state")


def fetch_weather(
    points_path: Path,
    output_path: Path,
    start_date: str,
    end_date: str,
    batch_size: int = 100,
    base_url: str = "https://api.open-meteo.com/v1/forecast",
    sleep_seconds: float = 0.2,
    max_retries: int = 5,
    retry_base_seconds: float = 30.0,
) -> int:
    """Fetch weather in batches and write normalized hourly rows."""
    with points_path.open("r", encoding="utf-8", newline="") as handle:
        points = list(csv.DictReader(handle))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["gdenr", "gdename", "latitude", "longitude", "time", *HOURLY_VARIABLES]
    rows_written = 0
    with output_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for offset in range(0, len(points), batch_size):
            batch = points[offset : offset + batch_size]
            payload = fetch_json(
                build_url(base_url, batch, start_date, end_date),
                max_retries=max_retries,
                retry_base_seconds=retry_base_seconds,
            )
            rows = normalize_response(payload, batch)
            writer.writerows(rows)
            rows_written += len(rows)
            if sleep_seconds and offset + batch_size < len(points):
                time.sleep(sleep_seconds)
    return rows_written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--base-url", default="https://api.open-meteo.com/v1/forecast")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--sleep-seconds", type=float, default=2.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-base-seconds", type=float, default=30.0)
    args = parser.parse_args()
    date.fromisoformat(args.start_date)
    date.fromisoformat(args.end_date)
    count = fetch_weather(
        args.points,
        args.output,
        args.start_date,
        args.end_date,
        args.batch_size,
        base_url=args.base_url,
        sleep_seconds=args.sleep_seconds,
        max_retries=args.max_retries,
        retry_base_seconds=args.retry_base_seconds,
    )
    print({"rows_written": count, "output": str(args.output)})


if __name__ == "__main__":
    main()
