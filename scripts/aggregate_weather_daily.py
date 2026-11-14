#!/usr/bin/env python3
"""Aggregate hourly municipality weather to one daily row per municipality."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


def aggregate_weather(input_path: Path, output_path: Path) -> int:
    """Aggregate temperature, precipitation, snow and wind by local date."""
    groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "rows": 0,
            "temperature": [],
            "precipitation": 0.0,
            "rain": 0.0,
            "snowfall": 0.0,
            "wind_max": 0.0,
            "bad_weather_hours": 0,
        }
    )
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row["gdenr"], row["time"][:10])
            item = groups[key]
            item["gdename"] = row["gdename"]
            item["rows"] = int(item["rows"]) + 1
            item["temperature"].append(float(row["temperature_2m"]))
            item["precipitation"] += float(row["precipitation"] or 0)
            item["rain"] += float(row["rain"] or 0)
            item["snowfall"] += float(row["snowfall"] or 0)
            item["wind_max"] = max(
                float(item["wind_max"]), float(row["wind_speed_10m"] or 0)
            )
            if (
                int(float(row["weather_code"] or 0)) >= 51
                or float(row["precipitation"] or 0) > 0
            ):
                item["bad_weather_hours"] += 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "gdenr",
        "gdename",
        "date",
        "hours",
        "average_temperature",
        "total_precipitation",
        "total_rain",
        "total_snowfall",
        "maximum_wind_speed",
        "bad_weather_hours",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for (gdenr, service_date), item in sorted(groups.items()):
            writer.writerow(
                {
                    "gdenr": gdenr,
                    "gdename": item["gdename"],
                    "date": service_date,
                    "hours": item["rows"],
                    "average_temperature": sum(item["temperature"])
                    / len(item["temperature"]),
                    "total_precipitation": item["precipitation"],
                    "total_rain": item["rain"],
                    "total_snowfall": item["snowfall"],
                    "maximum_wind_speed": item["wind_max"],
                    "bad_weather_hours": item["bad_weather_hours"],
                }
            )
    return len(groups)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        {"rows": aggregate_weather(args.input, args.output), "output": str(args.output)}
    )


if __name__ == "__main__":
    main()
