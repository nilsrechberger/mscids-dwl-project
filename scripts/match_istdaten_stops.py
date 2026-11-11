#!/usr/bin/env python3
"""Measure Ist-Daten stop identifier coverage against GTFS stops.csv."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_stop_keys(path: Path, encoding: str = "utf-8") -> dict[str, set[str]]:
    """Load identifier sets from the compact extracted stops.csv."""
    keys: dict[str, set[str]] = {
        "stop_id": set(),
        "original_stop_id": set(),
        "didok": set(),
    }
    with path.open("r", encoding=encoding, newline="") as handle:
        for row in csv.DictReader(handle):
            for column in keys:
                value = (row.get(column) or "").strip()
                if value:
                    keys[column].add(value)
    return keys


def candidate_keys(value: str | None) -> list[str]:
    """Return exact and seven-digit Didok candidates for a BPUIC-like value."""
    if not value:
        return []
    value = value.strip()
    candidates = [value]
    if value.isdigit() and len(value) == 9:
        candidates.append(value[:7])
    return candidates


def match_row(row: dict[str, str], keys: dict[str, set[str]]) -> str | None:
    """Return the matching identifier source, preferring SLOID/exact matches."""
    sloid = (row.get("SLOID") or "").strip()
    for value in [sloid]:
        if value and (value in keys["stop_id"] or value in keys["original_stop_id"]):
            return "sloid"
    bpuic = (row.get("BPUIC") or "").strip()
    for value in candidate_keys(bpuic):
        if value in keys["didok"]:
            return "bpuic_didok"
        if value in keys["stop_id"] or value in keys["original_stop_id"]:
            return "bpuic_stop_id"
    return None


def match_istdaten(
    istdaten_path: Path, stops_path: Path, output_dir: Path, encoding: str = "utf-8-sig"
) -> dict[str, Any]:
    """Stream the Ist-Daten file and write identifier coverage metrics."""
    keys = load_stop_keys(stops_path)
    delimiter = ","
    matched_by: Counter[str] = Counter()
    status_by_match: Counter[str] = Counter()
    unmatched_examples: list[dict[str, str]] = []
    rows = 0
    swiss_rows = 0

    with istdaten_path.open(
        "r", encoding=encoding, errors="replace", newline=""
    ) as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for raw_row in reader:
            row = {
                str(key).strip(): value or "" for key, value in raw_row.items() if key
            }
            rows += 1
            bpuic = row.get("BPUIC", "")
            if bpuic.startswith("85") or (row.get("SLOID", "").startswith("ch:")):
                swiss_rows += 1
            match = match_row(row, keys)
            matched_by[match or "unmatched"] += 1
            status = row.get("AN_PROGNOSE_STATUS", "") or "<NA>"
            status_by_match[f"{match or 'unmatched'}::{status}"] += 1
            if match is None and len(unmatched_examples) < 25:
                unmatched_examples.append(
                    {
                        "BPUIC": bpuic,
                        "SLOID": row.get("SLOID", ""),
                        "HALTESTELLEN_NAME": row.get("HALTESTELLEN_NAME", ""),
                    }
                )

    matched = rows - matched_by["unmatched"]
    profile: dict[str, Any] = {
        "istdaten_input": str(istdaten_path),
        "stops_input": str(stops_path),
        "istdaten_rows": rows,
        "rows_with_swiss_identifier": swiss_rows,
        "gtfs_stop_key_counts": {name: len(values) for name, values in keys.items()},
        "matched_rows": matched,
        "unmatched_rows": matched_by["unmatched"],
        "match_rate_all_rows": matched / rows if rows else None,
        "match_counts": dict(matched_by),
        "match_status_counts": dict(status_by_match),
        "unmatched_examples": unmatched_examples,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "stop_match_profile.json").write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_markdown(profile, output_dir / "stop_match_profile.md")
    return profile


def write_markdown(profile: dict[str, Any], path: Path) -> None:
    """Write a compact match report."""
    lines = [
        "# Ist-Daten to GTFS stop match",
        "",
        f"- Ist-Daten rows: `{profile['istdaten_rows']:,}`",
        f"- Rows with Swiss identifier: `{profile['rows_with_swiss_identifier']:,}`",
        f"- Matched rows: `{profile['matched_rows']:,}`",
        f"- Unmatched rows: `{profile['unmatched_rows']:,}`",
        f"- Match rate (all rows): `{profile['match_rate_all_rows']}`",
        "",
        "## Match method counts",
        "",
    ]
    for method, count in profile["match_counts"].items():
        lines.append(f"- `{method}`: `{count:,}`")
    lines.extend(["", "## Unmatched examples", ""])
    for row in profile["unmatched_examples"]:
        lines.append(f"- `{row}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--istdaten", type=Path, required=True)
    parser.add_argument("--stops", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path(".work/istdaten-stop-match")
    )
    args = parser.parse_args()
    profile = match_istdaten(args.istdaten, args.stops, args.output_dir)
    print(
        json.dumps(
            {
                key: profile[key]
                for key in [
                    "istdaten_rows",
                    "matched_rows",
                    "unmatched_rows",
                    "match_rate_all_rows",
                    "match_counts",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
