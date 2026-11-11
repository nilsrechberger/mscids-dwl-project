#!/usr/bin/env python3
"""Build stop-weighted representative weather points per municipality."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def build_points(stops_path: Path, output_path: Path) -> int:
    """Average GTFS stop coordinates for every assigned municipality."""
    sums: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    names: dict[str, str] = {}
    with stops_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            gdenr = (row.get("municipality_gdenr") or "").strip()
            if not gdenr:
                continue
            try:
                lat = float(row.get("stop_lat", ""))
                lon = float(row.get("stop_lon", ""))
            except ValueError:
                continue
            sums[gdenr][0] += lat
            sums[gdenr][1] += lon
            sums[gdenr][2] += 1
            names[gdenr] = row.get("municipality_name", "")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        fields = ["gdenr", "gdename", "latitude", "longitude", "stop_count"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for gdenr in sorted(sums):
            lat_sum, lon_sum, count = sums[gdenr]
            writer.writerow(
                {
                    "gdenr": gdenr,
                    "gdename": names[gdenr],
                    "latitude": f"{lat_sum / count:.6f}",
                    "longitude": f"{lon_sum / count:.6f}",
                    "stop_count": int(count),
                }
            )
    return len(sums)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stops", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        {
            "municipalities": build_points(args.stops, args.output),
            "output": str(args.output),
        }
    )


if __name__ == "__main__":
    main()
