"""Tests for the Ist-Daten v2 Silver normalization."""

import csv
from pathlib import Path

from scripts.normalize_istdaten_silver import normalize_csv, normalize_row


def source_row(**overrides: str) -> dict[str, str]:
    row = {
        "BETRIEBSTAG": "10.11.2026",
        "FAHRT_BEZEICHNER": "trip-1",
        "BETREIBER_ID": "85:1",
        "BETREIBER_ABK": "SBB",
        "BETREIBER_NAME": "Swiss Federal Railways",
        "PRODUKT_ID": "Train",
        "LINIEN_ID": "line-1",
        "LINIEN_TEXT": "S1",
        "UMLAUF_ID": "run-1",
        "VERKEHRSMITTEL_TEXT": "Train",
        "ZUSATZFAHRT_TF": "false",
        "FAELLT_AUS_TF": "false",
        "BPUIC": "8503000",
        "SLOID": "ch:1:sloid:3000:0:1",
        "HALTESTELLEN_NAME": "Zurich HB",
        "ANKUNFTSZEIT": "10.11.2026 08:00",
        "AN_PROGNOSE": "10.11.2026 08:01:00",
        "AN_PROGNOSE_STATUS": "REAL",
        "ABFAHRTSZEIT": "10.11.2026 08:01",
        "AB_PROGNOSE": "10.11.2026 08:02:00",
        "AB_PROGNOSE_STATUS": "REAL",
    }
    row.update(overrides)
    return row


def test_normalize_row_maps_fields_and_delays() -> None:
    result = normalize_row(source_row())

    assert result["operating_date"] == "2026-11-10"
    assert result["trip_id"] == "trip-1"
    assert result["stop_id_bpuic"] == "8503000"
    assert result["scheduled_arrival"] == "2026-11-10 08:00:00"
    assert result["predicted_arrival"] == "2026-11-10 08:01:00"
    assert result["arrival_delay_seconds"] == "60"
    assert result["arrival_delay_quality"] == "valid"
    assert result["arrival_usable_for_real_delay"] == "true"
    assert result["delay_quality"] == "valid"


def test_normalize_row_keeps_extreme_delay_but_marks_it() -> None:
    result = normalize_row(source_row(AN_PROGNOSE="10.11.2026 16:01:00"))

    assert result["arrival_delay_seconds"] == "28860"
    assert result["arrival_delay_quality"] == "extreme_outlier"
    assert result["arrival_usable_for_real_delay"] == "false"


def test_normalize_row_marks_cross_day_delay() -> None:
    result = normalize_row(
        source_row(
            ANKUNFTSZEIT="10.11.2026 23:59",
            AN_PROGNOSE="11.11.2026 00:01:00",
        )
    )

    assert result["arrival_delay_seconds"] == ""
    assert result["arrival_delay_quality"] == "cross_day_or_invalid"
    assert result["arrival_exclusion_reason"] == "timestamp_dates_differ"


def test_normalize_csv_detects_semicolon_and_streams_rows(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "silver.csv"
    rows = [source_row(), source_row(FAELLT_AUS_TF="true")]
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    result = normalize_csv(input_path, output_path)
    with output_path.open(encoding="utf-8", newline="") as handle:
        output_rows = list(csv.DictReader(handle))

    assert result["delimiter"] == ";"
    assert result["rows"] == 2
    assert result["cancelled_rows"] == 1
    assert len(output_rows) == 2
    assert output_rows[1]["is_cancelled"] == "true"
