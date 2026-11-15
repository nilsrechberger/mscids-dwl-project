"""Tests for daily municipality transport aggregation and Gold join."""

import csv
from pathlib import Path

from scripts.aggregate_silver_municipality_daily import aggregate
from scripts.join_municipality_daily import join_daily


def test_aggregate_silver_municipality_daily(tmp_path: Path) -> None:
    source = tmp_path / "mapped.csv"
    source.write_text(
        "operating_date,trip_id,is_cancelled,municipality_gdenr,municipality_name,arrival_delay_seconds,arrival_delay_quality,arrival_usable_for_real_delay\n"
        "2026-11-14,t1,false,1,Aeugst,60,valid,true\n"
        "2026-11-14,t2,true,1,Aeugst,420,valid,true\n"
        "2026-11-14,t2,true,,Unknown,60,valid,true\n",
        encoding="utf-8",
    )
    output = tmp_path / "daily.csv"

    assert aggregate(source, output) == 1
    with output.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["gdenr"] == "1"
    assert row["observations"] == "2"
    assert row["unique_trips"] == "2"
    assert row["cancelled"] == "1"
    assert row["late_arrival_rows_over_5m"] == "1"
    assert float(row["average_arrival_delay_seconds"]) == 240


def test_join_municipality_daily(tmp_path: Path) -> None:
    transport = tmp_path / "transport.csv"
    transport.write_text(
        "gdenr,gdename,date,observations\n1,Aeugst,2026-11-14,2\n",
        encoding="utf-8",
    )
    weather = tmp_path / "weather.csv"
    weather.write_text(
        "gdenr,gdename,date,hours,average_temperature,total_precipitation,total_rain,total_snowfall,maximum_wind_speed,bad_weather_hours\n1,Aeugst,2026-11-14,24,4.5,1.2,1.2,0,8,2\n",
        encoding="utf-8",
    )
    output = tmp_path / "gold.csv"

    assert join_daily(transport, weather, output) == 1
    with output.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["gdenr"] == "1"
    assert row["average_temperature"] == "4.5"
    assert row["bad_weather_hours"] == "2"
