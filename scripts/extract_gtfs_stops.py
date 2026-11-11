#!/usr/bin/env python3
"""Extract a compact stops.csv from an official GTFS Static ZIP."""

from __future__ import annotations

import argparse
import csv
import io
import zipfile
from pathlib import Path

OUTPUT_COLUMNS = [
    "stop_id",
    "stop_name",
    "stop_lat",
    "stop_lon",
    "original_stop_id",
    "didok",
]


def find_stops_member(archive: zipfile.ZipFile) -> str:
    """Find stops.txt even if the ZIP contains a top-level directory."""
    matches = [
        name
        for name in archive.namelist()
        if name.lower().endswith("/stops.txt") or name.lower() == "stops.txt"
    ]
    if not matches:
        raise FileNotFoundError("GTFS archive does not contain stops.txt")
    return matches[0]


def extract_stops(archive_path: Path, output_path: Path) -> int:
    """Extract selected stop columns and return the number of rows."""
    with zipfile.ZipFile(archive_path) as archive:
        member = find_stops_member(archive)
        with archive.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            missing = [
                column
                for column in OUTPUT_COLUMNS
                if column not in (reader.fieldnames or [])
            ]
            if missing:
                raise ValueError(f"stops.txt is missing columns: {missing}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8", newline="") as target:
                writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS)
                writer.writeheader()
                count = 0
                for row in reader:
                    writer.writerow(
                        {column: row.get(column, "") or "" for column in OUTPUT_COLUMNS}
                    )
                    count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True, dest="archive_path")
    parser.add_argument("--output", type=Path, required=True, dest="output_path")
    args = parser.parse_args()
    print(
        {
            "rows": extract_stops(args.archive_path, args.output_path),
            "output": str(args.output_path),
        }
    )


if __name__ == "__main__":
    main()
