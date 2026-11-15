"""Tests for the Silver-to-municipality stop join."""

import csv
from pathlib import Path

from scripts.join_istdaten_municipalities import (
    join_istdaten,
    load_stop_index,
    match_stop,
)


def test_sloid_is_preferred_over_bpuic(tmp_path: Path) -> None:
    stops = tmp_path / "stops.csv"
    stops.write_text(
        "stop_id,stop_name,stop_lat,stop_lon,original_stop_id,didok,municipality_gdenr,municipality_name\n"
        "sloid-a,Stop A,47.1,8.1,sloid-a,8503000,1,Aeugst\n"
        "8503000,Stop B,47.2,8.2,8503000,8503000,2,Other\n",
        encoding="utf-8",
    )
    index = load_stop_index(stops)
    metadata, method = match_stop(
        {"stop_id_sloid": "sloid-a", "stop_id_bpuic": "8503000"}, index
    )

    assert method == "sloid"
    assert metadata["municipality_gdenr"] == "1"


def test_bpuic_nine_digit_falls_back_to_seven_digit(tmp_path: Path) -> None:
    stops = tmp_path / "stops.csv"
    stops.write_text(
        "stop_id,stop_name,stop_lat,stop_lon,original_stop_id,didok,municipality_gdenr,municipality_name\n"
        "8503000,Stop,47.1,8.1,8503000,8503000,1,Aeugst\n",
        encoding="utf-8",
    )
    metadata, method = match_stop(
        {"stop_id_sloid": "", "stop_id_bpuic": "850300002"},
        load_stop_index(stops),
    )

    assert method == "bpuic"
    assert metadata["municipality_name"] == "Aeugst"


def test_join_writes_municipality_fields(tmp_path: Path) -> None:
    silver = tmp_path / "silver.csv"
    silver.write_text(
        "operating_date,stop_id_bpuic,stop_id_sloid\n"
        "2026-11-14,8503000,\n"
        "2026-11-14,8002140,\n",
        encoding="utf-8",
    )
    stops = tmp_path / "stops.csv"
    stops.write_text(
        "stop_id,stop_name,stop_lat,stop_lon,original_stop_id,didok,municipality_gdenr,municipality_name\n"
        "8503000,Stop,47.1,8.1,8503000,8503000,1,Aeugst\n",
        encoding="utf-8",
    )
    output = tmp_path / "joined.csv"

    result = join_istdaten(silver, stops, output)
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert result["matched_rows"] == 1
    assert result["unmatched_rows"] == 1
    assert rows[0]["municipality_gdenr"] == "1"
    assert rows[0]["stop_match_method"] == "bpuic"
    assert rows[1]["stop_match_method"] == "unmatched"
