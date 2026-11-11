"""Tests for daily weather aggregation and the transport/weather join."""

import csv
import json
from pathlib import Path

from scripts.aggregate_weather_daily import aggregate_weather
from scripts.join_daily_analysis import join_daily


def test_aggregate_weather_daily(tmp_path: Path) -> None:
    source = tmp_path / "weather.csv"
    source.write_text(
        "gdenr,gdename,latitude,longitude,time,temperature_2m,precipitation,rain,snowfall,wind_speed_10m,weather_code\n"
        "261,Zürich,47.37,8.54,2026-11-10T00:00,10,1.0,1.0,0,5,61\n"
        "261,Zürich,47.37,8.54,2026-11-10T01:00,12,0.5,0.5,0,8,3\n",
        encoding="utf-8",
    )
    output = tmp_path / "weather_daily.csv"

    assert aggregate_weather(source, output) == 1
    with output.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["gdenr"] == "261"
    assert row["date"] == "2026-11-10"
    assert row["hours"] == "2"
    assert float(row["average_temperature"]) == 11
    assert float(row["total_precipitation"]) == 1.5
    assert row["bad_weather_hours"] == "2"


def test_join_daily(tmp_path: Path) -> None:
    transport = tmp_path / "transport.json"
    transport.write_text(
        json.dumps(
            [
                {
                    "gdenr": "261",
                    "gdename": "Zürich",
                    "service_dates": ["2026-11-10"],
                    "observations": 100,
                    "unique_trips": 10,
                    "cancelled": 2,
                    "cancellation_rate": 0.02,
                }
            ]
        ),
        encoding="utf-8",
    )
    weather = tmp_path / "weather_daily.csv"
    weather.write_text(
        "gdenr,gdename,date,average_temperature,total_precipitation,total_snowfall,maximum_wind_speed,bad_weather_hours\n"
        "261,Zürich,2026-11-10,11,1.5,0,8,1\n",
        encoding="utf-8",
    )
    output = tmp_path / "analysis.csv"

    assert join_daily(transport, weather, output) == 1
    with output.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["gdename"] == "Zürich"
    assert row["date"] == "2026-11-10"
    assert row["observations"] == "100"
    assert row["total_precipitation"] == "1.5"
