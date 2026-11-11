#!/usr/bin/env python3
"""Profile an Ist-Daten v2 CSV without loading the full file into memory."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

INTEREST_COLUMNS = [
    "BETRIEBSTAG",
    "FAHRT_BEZEICHNER",
    "BETREIBER_ID",
    "BETREIBER_ABK",
    "BETREIBER_NAME",
    "PRODUKT_ID",
    "LINIEN_ID",
    "LINIEN_TEXT",
    "UMLAUF_ID",
    "VERKEHRSMITTEL_TEXT",
    "BPUIC",
    "SLOID",
    "HALTESTELLEN_NAME",
    "ANKUNFTSZEIT",
    "AN_PROGNOSE",
    "AN_PROGNOSE_STATUS",
    "ABFAHRTSZEIT",
    "AB_PROGNOSE",
    "AB_PROGNOSE_STATUS",
    "FAELLT_AUS_TF",
    "DURCHFAHRT_TF",
    "ZUSATZFAHRT_TF",
]
VALUE_COLUMNS = {
    "AN_PROGNOSE_STATUS",
    "AB_PROGNOSE_STATUS",
    "FAELLT_AUS_TF",
    "PRODUKT_ID",
    "DURCHFAHRT_TF",
    "ZUSATZFAHRT_TF",
}


def detect_delimiter(path: Path, encoding: str) -> str:
    """Detect the CSV delimiter from the first 64 KiB."""
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        sample = handle.read(65536)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def clean(value: str | None) -> str:
    """Represent blank values consistently in profile output."""
    return "<NA>" if value is None or value == "" else value


def parse_time(value: str | None) -> datetime | None:
    """Parse the date/time formats used by Ist-Daten v2."""
    if not value:
        return None
    for pattern in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return None


def profile_csv(
    path: Path, output_dir: Path, encoding: str = "utf-8-sig"
) -> dict[str, Any]:
    """Profile a potentially large CSV row by row."""
    delimiter = detect_delimiter(path, encoding)
    row_count = 0
    columns: list[str] = []
    selected: list[str] = []
    null_counts: Counter[str] = Counter()
    value_counts: dict[str, Counter[str]] = {
        column: Counter() for column in VALUE_COLUMNS
    }
    unique_trips: set[str] = set()
    unique_bpuic: set[str] = set()
    unique_sloid: set[str] = set()
    swiss_bpuic = 0
    foreign_bpuic = 0
    delay_count = 0
    delay_sum = 0.0
    delay_min: float | None = None
    delay_max: float | None = None
    sample_rows: list[dict[str, str]] = []

    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        columns = [column.strip() for column in (reader.fieldnames or [])]
        selected = [column for column in INTEREST_COLUMNS if column in columns]
        for raw_row in reader:
            row = {str(key).strip(): value for key, value in raw_row.items() if key}
            row_count += 1
            if len(sample_rows) < 10:
                sample_rows.append(row)
            trip = clean(row.get("FAHRT_BEZEICHNER"))
            bpuic = clean(row.get("BPUIC"))
            sloid = clean(row.get("SLOID"))
            if trip != "<NA>":
                unique_trips.add(trip)
            if bpuic != "<NA>":
                unique_bpuic.add(bpuic)
                if bpuic.startswith("85"):
                    swiss_bpuic += 1
                else:
                    foreign_bpuic += 1
            if sloid != "<NA>":
                unique_sloid.add(sloid)
            for column in selected:
                value = row.get(column)
                if value is None or value == "":
                    null_counts[column] += 1
                if column in value_counts:
                    value_counts[column][clean(value)] += 1
            scheduled = parse_time(row.get("ANKUNFTSZEIT"))
            forecast = parse_time(row.get("AN_PROGNOSE"))
            if scheduled and forecast:
                delay = (forecast - scheduled).total_seconds()
                delay_count += 1
                delay_sum += delay
                delay_min = delay if delay_min is None else min(delay_min, delay)
                delay_max = delay if delay_max is None else max(delay_max, delay)

    metrics = {
        "unique_trips": len(unique_trips),
        "unique_bpuic": len(unique_bpuic),
        "unique_sloid": len(unique_sloid),
        "rows_with_swiss_bpuic_prefix_85": swiss_bpuic,
        "rows_with_non_swiss_bpuic_prefix": foreign_bpuic,
        "arrival_delay_rows": delay_count,
        "arrival_delay_mean_seconds": delay_sum / delay_count if delay_count else None,
        "arrival_delay_min_seconds": delay_min,
        "arrival_delay_max_seconds": delay_max,
    }
    profile: dict[str, Any] = {
        "input": str(path),
        "file_size_bytes": path.stat().st_size,
        "encoding": encoding,
        "delimiter": delimiter,
        "row_count": row_count,
        "column_count": len(columns),
        "columns": columns,
        "interest_columns_found": selected,
        "interest_columns_missing": [c for c in INTEREST_COLUMNS if c not in columns],
        "null_counts": dict(null_counts),
        "top_values": {
            c: dict(counter.most_common(20))
            for c, counter in value_counts.items()
            if c in selected
        },
        "metrics": metrics,
        "sample_rows": sample_rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "profile.json").write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_markdown(profile, output_dir / "profile.md")
    return profile


def write_markdown(profile: dict[str, Any], path: Path) -> None:
    """Write a human-readable summary next to the JSON profile."""
    lines = [
        "# Ist-Daten v2 profile",
        "",
        f"- Input: `{profile['input']}`",
        f"- File size: `{profile['file_size_bytes']:,}` bytes",
        f"- Rows: `{profile['row_count']:,}`",
        f"- Columns: `{profile['column_count']}`",
        f"- Delimiter: `{profile['delimiter']}`",
        f"- Encoding: `{profile['encoding']}`",
        "",
        "## Expected columns",
        "",
        f"- Found: {', '.join(profile['interest_columns_found']) or 'none'}",
        f"- Missing: {', '.join(profile['interest_columns_missing']) or 'none'}",
        "",
        "## Key metrics",
        "",
    ]
    for key, value in profile["metrics"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Null counts", ""])
    for column, count in profile["null_counts"].items():
        lines.append(f"- `{column}`: `{count:,}`")
    lines.extend(["", "## Top values", ""])
    for column, values in profile["top_values"].items():
        lines.append(f"### `{column}`")
        for value, count in values.items():
            lines.append(f"- `{value}`: `{count:,}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Local CSV file")
    parser.add_argument(
        "--output-dir", type=Path, default=Path(".work/istdaten-profile")
    )
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()
    profile = profile_csv(args.input, args.output_dir, args.encoding)
    print(
        json.dumps(
            {
                key: profile[key]
                for key in [
                    "row_count",
                    "column_count",
                    "delimiter",
                    "interest_columns_missing",
                    "metrics",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
