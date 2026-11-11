#!/usr/bin/env python3
"""Profile delay quality classes on an Ist-Daten v2 CSV."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

try:
    from scripts.delay_quality import classify_delay
except ModuleNotFoundError:
    from delay_quality import classify_delay


def profile(path: Path, output: Path) -> dict[str, object]:
    """Count quality classes without materializing the full data set."""
    quality: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    valid_real = 0
    rows = 0
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for raw in csv.DictReader(handle, delimiter=";"):
            row = {str(key).strip(): value or "" for key, value in raw.items() if key}
            result = classify_delay(
                row.get("ANKUNFTSZEIT"),
                row.get("AN_PROGNOSE"),
                row.get("AN_PROGNOSE_STATUS"),
            )
            rows += 1
            quality[result["delay_quality"]] += 1
            reasons[result["delay_exclusion_reason"]] += 1
            statuses[result["status"]] += 1
            valid_real += int(result["usable_for_real_delay"])
    result = {
        "rows": rows,
        "quality_counts": dict(quality),
        "exclusion_reason_counts": dict(reasons),
        "status_counts": dict(statuses),
        "usable_for_real_delay": valid_real,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(profile(args.input, args.output), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
