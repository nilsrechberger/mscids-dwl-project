#!/usr/bin/env python3
"""Aggregate municipality-enriched Silver transport rows by day."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any


def aggregate(input_path: Path, output_path: Path) -> int:
    """Aggregate only rows with a resolved BFS municipality."""
    groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "trips": set(),
            "observations": 0,
            "cancelled": 0,
            "delay_count": 0,
            "delay_sum": 0.0,
            "late_count": 0,
            "real_delay_count": 0,
        }
    )
    with input_path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            gdenr = (row.get("municipality_gdenr") or "").strip()
            date = (row.get("operating_date") or "").strip()
            if not gdenr or not date:
                continue
            item = groups[(gdenr, date)]
            item["gdename"] = row.get("municipality_name", "")
            item["observations"] += 1
            trip = (row.get("trip_id") or "").strip()
            if trip:
                item["trips"].add(trip)
            if row.get("is_cancelled") == "true":
                item["cancelled"] += 1
            delay = (row.get("arrival_delay_seconds") or "").strip()
            if delay and row.get("arrival_delay_quality") == "valid":
                value = float(delay)
                item["delay_count"] += 1
                item["delay_sum"] += value
                if value > 300:
                    item["late_count"] += 1
                if row.get("arrival_usable_for_real_delay") == "true":
                    item["real_delay_count"] += 1

    fields = [
        "gdenr",
        "gdename",
        "date",
        "observations",
        "unique_trips",
        "cancelled",
        "cancellation_rate",
        "valid_arrival_delay_rows",
        "average_arrival_delay_seconds",
        "late_arrival_rows_over_5m",
        "real_arrival_delay_rows",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for (gdenr, date), item in sorted(groups.items()):
            observations = int(item["observations"])
            delay_count = int(item["delay_count"])
            writer.writerow(
                {
                    "gdenr": gdenr,
                    "gdename": item["gdename"],
                    "date": date,
                    "observations": observations,
                    "unique_trips": len(item["trips"]),
                    "cancelled": item["cancelled"],
                    "cancellation_rate": item["cancelled"] / observations,
                    "valid_arrival_delay_rows": delay_count,
                    "average_arrival_delay_seconds": (
                        item["delay_sum"] / delay_count if delay_count else ""
                    ),
                    "late_arrival_rows_over_5m": item["late_count"],
                    "real_arrival_delay_rows": item["real_delay_count"],
                }
            )
    return len(groups)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print({"rows": aggregate(args.input, args.output), "output": str(args.output)})


if __name__ == "__main__":
    main()
