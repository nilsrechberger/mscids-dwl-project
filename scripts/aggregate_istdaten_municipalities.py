#!/usr/bin/env python3
"""Aggregate Ist-Daten v2 rows by municipality using enriched GTFS stops."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def add_key(
    mapping: dict[str, tuple[str, str]], value: str, municipality: tuple[str, str]
) -> None:
    if value:
        mapping.setdefault(value, municipality)
        if value.isdigit() and len(value) == 9:
            mapping.setdefault(value[:7], municipality)


def normalize_service_date(value: str) -> str:
    """Convert Ist-Daten's DD.MM.YYYY date to ISO YYYY-MM-DD."""
    parts = value.split(".")
    if len(parts) == 3 and len(parts[2]) == 4:
        return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    return value


def load_stop_municipalities(path: Path) -> dict[str, tuple[str, str]]:
    """Build exact SLOID/stop_id/didok lookup keys."""
    lookup: dict[str, tuple[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            municipality = row.get("municipality_gdenr", "")
            if not municipality:
                continue
            municipality_value = (municipality, row.get("municipality_name", ""))
            for column in ("stop_id", "original_stop_id", "didok"):
                add_key(lookup, (row.get(column) or "").strip(), municipality_value)
    return lookup


def municipality_key(
    row: dict[str, str], lookup: dict[str, tuple[str, str]]
) -> tuple[str, str]:
    """Match SLOID first, then BPUIC and its seven-digit variant."""
    for column in ("SLOID", "BPUIC"):
        value = (row.get(column) or "").strip()
        if value in lookup:
            return lookup[value]
        if value.isdigit() and len(value) == 9 and value[:7] in lookup:
            return lookup[value[:7]]
    return "", ""


def aggregate(
    istdaten_path: Path, stops_path: Path, output_dir: Path
) -> dict[str, Any]:
    lookup = load_stop_municipalities(stops_path)
    aggregates: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "observations": 0,
            "trips": set(),
            "service_dates": set(),
            "cancelled": 0,
            "arrival_status": defaultdict(int),
            "products": defaultdict(int),
        }
    )
    rows = matched = 0
    with istdaten_path.open(
        "r", encoding="utf-8-sig", errors="replace", newline=""
    ) as handle:
        for raw in csv.DictReader(handle, delimiter=";"):
            row = {str(key).strip(): value or "" for key, value in raw.items() if key}
            rows += 1
            gdenr, gdename = municipality_key(row, lookup)
            if not gdenr:
                continue
            matched += 1
            item = aggregates[gdenr]
            item["gdename"] = gdename
            item["observations"] += 1
            if row.get("BETRIEBSTAG"):
                item["service_dates"].add(normalize_service_date(row["BETRIEBSTAG"]))
            if row.get("FAHRT_BEZEICHNER"):
                item["trips"].add(row["FAHRT_BEZEICHNER"])
            if row.get("FAELLT_AUS_TF", "").lower() == "true":
                item["cancelled"] += 1
            item["arrival_status"][row.get("AN_PROGNOSE_STATUS") or "<NA>"] += 1
            item["products"][row.get("PRODUKT_ID") or "<NA>"] += 1

    records = []
    for gdenr, item in aggregates.items():
        records.append(
            {
                "gdenr": gdenr,
                "gdename": item["gdename"],
                "service_dates": sorted(item["service_dates"]),
                "observations": item["observations"],
                "unique_trips": len(item["trips"]),
                "cancelled": item["cancelled"],
                "cancellation_rate": (
                    item["cancelled"] / item["observations"]
                    if item["observations"]
                    else None
                ),
                "arrival_status": dict(item["arrival_status"]),
                "products": dict(item["products"]),
            }
        )
    records.sort(key=lambda item: (-item["observations"], item["gdenr"]))
    profile = {
        "istdaten_rows": rows,
        "municipality_matched_rows": matched,
        "municipality_match_rate": matched / rows if rows else None,
        "municipalities_with_observations": len(records),
        "municipalities_at_least_500_observations": sum(
            item["observations"] >= 500 for item in records
        ),
        "top_municipalities": records[:20],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "municipality_aggregates.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "municipality_profile.json").write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with (output_dir / "municipality_aggregates.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        fields = [
            "gdenr",
            "gdename",
            "service_dates",
            "observations",
            "unique_trips",
            "cancelled",
            "cancellation_rate",
            "arrival_status",
            "products",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in records:
            writer.writerow(
                {
                    **item,
                    "service_dates": json.dumps(
                        item["service_dates"], ensure_ascii=False
                    ),
                    "arrival_status": json.dumps(
                        item["arrival_status"], ensure_ascii=False
                    ),
                    "products": json.dumps(item["products"], ensure_ascii=False),
                }
            )
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--istdaten", type=Path, required=True)
    parser.add_argument("--stops", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            aggregate(args.istdaten, args.stops, args.output_dir),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
