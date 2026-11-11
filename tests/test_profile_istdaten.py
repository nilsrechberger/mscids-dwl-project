"""Tests for the local Ist-Daten v2 profiling spike."""

from pathlib import Path

from scripts.aggregate_istdaten_municipalities import normalize_service_date
from scripts.profile_istdaten import profile_csv


def test_profile_csv(tmp_path: Path) -> None:
    """Profiles a small CSV and writes machine/human-readable results."""
    source = Path(__file__).parent / "fixtures" / "sample_istdaten.csv"
    profile = profile_csv(source, tmp_path)

    assert profile["row_count"] == 3
    assert profile["delimiter"] == ","
    assert "BPUIC" in profile["interest_columns_found"]
    assert profile["interest_columns_missing"] == []
    assert profile["metrics"]["unique_trips"] == 3
    assert profile["metrics"]["unique_bpuic"] == 2
    assert profile["metrics"]["unique_sloid"] == 1
    assert profile["metrics"]["arrival_delay_rows"] == 2
    assert (tmp_path / "profile.json").exists()
    assert (tmp_path / "profile.md").exists()


def test_normalize_service_date() -> None:
    """Converts the source date format to the shared ISO join key."""
    assert normalize_service_date("10.11.2026") == "2026-11-10"
