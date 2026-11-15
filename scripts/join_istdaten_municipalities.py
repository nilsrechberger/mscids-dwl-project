#!/usr/bin/env python3
"""Join normalized Ist-Daten rows to GTFS stops and BFS municipalities."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

JOIN_COLUMNS = [
    "matched_stop_id",
    "matched_stop_lat",
    "matched_stop_lon",
    "municipality_gdenr",
    "municipality_name",
    "stop_match_method",
]


def candidate_bpuic_keys(value: str) -> list[str]:
    """Return exact and seven-digit candidates for a BPUIC value."""
    value = value.strip()
    if not value:
        return []
    candidates = [value]
    if value.isdigit() and len(value) == 9:
        candidates.append(value[:7])
    return candidates


def load_stop_index(path: Path) -> dict[str, dict[str, str]]:
    """Load compact GTFS stop metadata indexed by SLOID and BPUIC variants."""
    index: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            metadata = {
                "matched_stop_id": (row.get("stop_id") or "").strip(),
                "matched_stop_lat": (row.get("stop_lat") or "").strip(),
                "matched_stop_lon": (row.get("stop_lon") or "").strip(),
                "municipality_gdenr": (row.get("municipality_gdenr") or "").strip(),
                "municipality_name": (row.get("municipality_name") or "").strip(),
            }
            keys = [
                (row.get("stop_id") or "").strip(),
                (row.get("original_stop_id") or "").strip(),
                (row.get("didok") or "").strip(),
            ]
            for key in keys:
                if key and key not in index:
                    index[key] = metadata
    return index


def match_stop(
    row: dict[str, str], index: dict[str, dict[str, str]]
) -> tuple[dict[str, str], str]:
    """Match SLOID first, then exact or seven-digit BPUIC."""
    sloid = row.get("stop_id_sloid", "").strip()
    for key in (sloid,):
        if key and key in index:
            return index[key], "sloid"

    bpuic = row.get("stop_id_bpuic", "").strip()
    for key in candidate_bpuic_keys(bpuic):
        if key in index:
            return index[key], "bpuic"

    return {
        column: "" for column in JOIN_COLUMNS if column != "stop_match_method"
    }, "unmatched"


def join_istdaten(
    silver_path: Path, stops_path: Path, output_path: Path
) -> dict[str, Any]:
    """Stream Silver rows, append stop/municipality fields, and write a CSV."""
    index = load_stop_index(stops_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counters: Counter[str] = Counter()
    with silver_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as source, output_path.open("w", encoding="utf-8", newline="") as target:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or []) + JOIN_COLUMNS
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for raw in reader:
            row = {str(key): value or "" for key, value in raw.items() if key}
            metadata, method = match_stop(row, index)
            row.update(metadata)
            row["stop_match_method"] = method
            writer.writerow(row)
            counters[method] += 1
            if row.get("municipality_gdenr"):
                counters["municipality_assigned"] += 1
            else:
                counters["municipality_unassigned"] += 1
            counters["rows"] += 1

    return {
        "silver_rows": counters["rows"],
        "stop_index_keys": len(index),
        "matched_rows": counters["sloid"] + counters["bpuic"],
        "unmatched_rows": counters["unmatched"],
        "match_rate": (
            (counters["sloid"] + counters["bpuic"]) / counters["rows"]
            if counters["rows"]
            else None
        ),
        "municipality_assigned_rows": counters["municipality_assigned"],
        "municipality_unassigned_rows": counters["municipality_unassigned"],
        "match_methods": {
            key: counters[key] for key in ("sloid", "bpuic", "unmatched")
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--silver", type=Path, required=True)
    parser.add_argument("--stops", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(join_istdaten(args.silver, args.stops, args.output), indent=2))


if __name__ == "__main__":
    main()
