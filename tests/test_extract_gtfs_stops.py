"""Tests for extracting stops.txt from a GTFS ZIP."""

import zipfile
from pathlib import Path

from scripts.extract_gtfs_stops import extract_stops


def test_extract_stops(tmp_path: Path) -> None:
    archive_path = tmp_path / "gtfs.zip"
    output_path = tmp_path / "stops.csv"
    content = (
        "stop_id,stop_name,stop_lat,stop_lon,original_stop_id,didok\n"
        "8503000:0:1,Zurich HB,47.3785,8.5367,ch:1:sloid:3000:0:1,8503000\n"
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("stops.txt", content)

    assert extract_stops(archive_path, output_path) == 1
    assert "8503000" in output_path.read_text(encoding="utf-8")
