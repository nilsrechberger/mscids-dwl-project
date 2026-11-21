"""Tests for daily weather aggregation."""

import csv
from pathlib import Path

from scripts.aggregate_weather_daily import aggregate_weather


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
