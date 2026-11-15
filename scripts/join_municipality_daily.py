#!/usr/bin/env python3
"""Join daily municipality transport and weather aggregates."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def join_daily(transport_path: Path, weather_path: Path, output_path: Path) -> int:
    """Join by stable BFS municipality number and ISO date."""
    weather: dict[tuple[str, str], dict[str, str]] = {}
    with weather_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            weather[(row.get("gdenr", ""), row.get("date", ""))] = row

    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with transport_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as source, output_path.open("w", encoding="utf-8", newline="") as target:
        reader = csv.DictReader(source)
        transport_fields = list(reader.fieldnames or [])
        weather_fields = [
            "hours",
            "average_temperature",
            "total_precipitation",
            "total_rain",
            "total_snowfall",
            "maximum_wind_speed",
            "bad_weather_hours",
        ]
        writer = csv.DictWriter(target, fieldnames=transport_fields + weather_fields)
        writer.writeheader()
        for row in reader:
            weather_row = weather.get((row.get("gdenr", ""), row.get("date", "")))
            if weather_row is None:
                continue
            row.update({field: weather_row.get(field, "") for field in weather_fields})
            writer.writerow(row)
            count += 1
    return count


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
