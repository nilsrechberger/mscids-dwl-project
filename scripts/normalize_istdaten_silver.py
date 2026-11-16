#!/usr/bin/env python3
"""Normalize Ist-Daten v2 into an English, analysis-ready Silver CSV."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.delay_quality import classify_delay, parse_istdaten_time

OUTPUT_COLUMNS = [
    "operating_date",
    "trip_id",
    "operator_id",
    "operator_abbreviation",
    "operator_name",
    "product_id",
    "line_id",
    "line_text",
    "run_id",
    "vehicle_type",
    "is_additional_trip",
    "is_cancelled",
    "stop_id_bpuic",
    "stop_id_sloid",
    "stop_name",
    "scheduled_arrival",
    "predicted_arrival",
    "arrival_forecast_status",
    "arrival_delay_seconds",
    "arrival_delay_quality",
    "arrival_exclusion_reason",
    "arrival_usable_for_real_delay",
    "scheduled_departure",
    "predicted_departure",
    "departure_forecast_status",
    "departure_delay_seconds",
    "departure_delay_quality",
    "departure_exclusion_reason",
    "departure_usable_for_real_delay",
    "delay_quality",
    "delay_exclusion_reason",
]

FIELD_MAP = {
    "BETRIEBSTAG": "operating_date",
    "FAHRT_BEZEICHNER": "trip_id",
    "BETREIBER_ID": "operator_id",
    "BETREIBER_ABK": "operator_abbreviation",
    "BETREIBER_NAME": "operator_name",
    "PRODUKT_ID": "product_id",
    "LINIEN_ID": "line_id",
    "LINIEN_TEXT": "line_text",
    "UMLAUF_ID": "run_id",
    "VERKEHRSMITTEL_TEXT": "vehicle_type",
    "ZUSATZFAHRT_TF": "is_additional_trip",
    "FAELLT_AUS_TF": "is_cancelled",
    "BPUIC": "stop_id_bpuic",
    "SLOID": "stop_id_sloid",
    "HALTESTELLEN_NAME": "stop_name",
}


def detect_delimiter(path: Path, encoding: str = "utf-8-sig") -> str:
    """Detect the delimiter from a small sample without loading the file."""
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        sample = handle.read(65536)
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|,").delimiter
    except csv.Error:
        return ";"


def clean(value: Any) -> str:
    """Convert missing values to an empty string and trim text values."""
    return "" if value is None else str(value).strip()


def parse_operating_date(value: str) -> str:
    """Convert DD.MM.YYYY to ISO date, preserving invalid values as blank."""
    try:
        return datetime.strptime(value, "%d.%m.%Y").date().isoformat()
    except ValueError:
        return ""


def iso_timestamp(value: str) -> str:
    """Convert an Ist-Daten timestamp to ISO-8601 text."""
    parsed = parse_istdaten_time(value)
    return parsed.isoformat(sep=" ") if parsed else ""


def bool_text(value: str) -> str:
    """Normalize source booleans to lowercase true/false or blank."""
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "ja"}:
        return "true"
    if normalized in {"false", "0", "no", "nein"}:
        return "false"
    return ""


def _delay_fields(scheduled: str, forecast: str, status: str) -> dict[str, str]:
    result = classify_delay(scheduled, forecast, status)
    delay = result["delay_raw_seconds"]
    return {
        "delay_seconds": "" if delay is None else str(delay),
        "delay_quality": str(result["delay_quality"]),
        "exclusion_reason": str(result["delay_exclusion_reason"]),
        "usable_for_real_delay": str(result["usable_for_real_delay"]).lower(),
    }


def normalize_row(raw: dict[str, Any]) -> dict[str, str]:
    """Map one German source row to the canonical Silver representation."""
    row = {str(key).strip(): clean(value) for key, value in raw.items() if key}
    normalized = {target: row.get(source, "") for source, target in FIELD_MAP.items()}
    normalized["operating_date"] = parse_operating_date(row.get("BETRIEBSTAG", ""))
    normalized["is_additional_trip"] = bool_text(row.get("ZUSATZFAHRT_TF", ""))
    normalized["is_cancelled"] = bool_text(row.get("FAELLT_AUS_TF", ""))

    arrival = _delay_fields(
        row.get("ANKUNFTSZEIT", ""),
        row.get("AN_PROGNOSE", ""),
        row.get("AN_PROGNOSE_STATUS", ""),
    )
    departure = _delay_fields(
        row.get("ABFAHRTSZEIT", ""),
        row.get("AB_PROGNOSE", ""),
        row.get("AB_PROGNOSE_STATUS", ""),
    )
    normalized.update(
        {
            "scheduled_arrival": iso_timestamp(row.get("ANKUNFTSZEIT", "")),
            "predicted_arrival": iso_timestamp(row.get("AN_PROGNOSE", "")),
            "arrival_forecast_status": clean(row.get("AN_PROGNOSE_STATUS", "")),
            "arrival_delay_seconds": arrival["delay_seconds"],
            "arrival_delay_quality": arrival["delay_quality"],
            "arrival_exclusion_reason": arrival["exclusion_reason"],
            "arrival_usable_for_real_delay": arrival["usable_for_real_delay"],
            "scheduled_departure": iso_timestamp(row.get("ABFAHRTSZEIT", "")),
            "predicted_departure": iso_timestamp(row.get("AB_PROGNOSE", "")),
            "departure_forecast_status": clean(row.get("AB_PROGNOSE_STATUS", "")),
            "departure_delay_seconds": departure["delay_seconds"],
            "departure_delay_quality": departure["delay_quality"],
            "departure_exclusion_reason": departure["exclusion_reason"],
            "departure_usable_for_real_delay": departure["usable_for_real_delay"],
        }
    )

    has_arrival = bool(row.get("ANKUNFTSZEIT") or row.get("AN_PROGNOSE"))
    normalized["delay_quality"] = (
        arrival["delay_quality"] if has_arrival else departure["delay_quality"]
    )
    normalized["delay_exclusion_reason"] = (
        arrival["exclusion_reason"] if has_arrival else departure["exclusion_reason"]
    )
    return {column: normalized.get(column, "") for column in OUTPUT_COLUMNS}


def normalize_csv(
    input_path: Path, output_path: Path, encoding: str = "utf-8-sig"
) -> dict[str, int | str]:
    """Normalize a large CSV row by row and return processing counters."""
    delimiter = detect_delimiter(input_path, encoding)
    counters: Counter[str] = Counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with input_path.open(
        "r", encoding=encoding, errors="replace", newline=""
    ) as source:
        reader = csv.DictReader(source, delimiter=delimiter)
        missing = [
            column for column in FIELD_MAP if column not in (reader.fieldnames or [])
        ]
        if missing:
            raise ValueError(f"Missing required source columns: {', '.join(missing)}")
        with output_path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for raw in reader:
                row = normalize_row(raw)
                writer.writerow(row)
                counters["rows"] += 1
                counters[f"delay_quality:{row['delay_quality']}"] += 1
                if row["is_cancelled"] == "true":
                    counters["cancelled_rows"] += 1
    return {"delimiter": delimiter, **dict(counters)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()
    print(json.dumps(normalize_csv(args.input, args.output, args.encoding), indent=2))


if __name__ == "__main__":
    main()
