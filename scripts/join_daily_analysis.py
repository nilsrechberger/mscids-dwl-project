#!/usr/bin/env python3
"""Join daily municipality transport aggregates with daily weather."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def join_daily(transport_path: Path, weather_path: Path, output_path: Path) -> int:
    """Join the one-day local spike outputs by municipality and date."""
    weather: dict[tuple[str, str], dict[str, str]] = {}
    with weather_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            weather[(row["gdenr"], row["date"])] = row
    transport = json.loads(transport_path.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []
    for item in transport:
        for service_date_raw in item.get("service_dates", []):
            date = service_date_raw[:10]
            weather_row = weather.get((item["gdenr"], date))
            if not weather_row:
                continue
            rows.append(
                {
                    "gdenr": item["gdenr"],
                    "gdename": item["gdename"],
                    "date": date,
                    "observations": str(item["observations"]),
                    "unique_trips": str(item["unique_trips"]),
                    "cancelled": str(item["cancelled"]),
                    "cancellation_rate": str(item["cancellation_rate"]),
                    "average_temperature": weather_row["average_temperature"],
                    "total_precipitation": weather_row["total_precipitation"],
                    "total_snowfall": weather_row["total_snowfall"],
                    "maximum_wind_speed": weather_row["maximum_wind_speed"],
                    "bad_weather_hours": weather_row["bad_weather_hours"],
                }
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["gdenr", "gdename", "date"]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--weather", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        {
            "rows": join_daily(args.transport, args.weather, args.output),
            "output": str(args.output),
        }
    )


if __name__ == "__main__":
    main()
