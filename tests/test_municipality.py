"""Test file for municipality.py"""

from pathlib import Path

from src.loaders.municipality import fetch_municipality


def test_fetch_municipality() -> None:
    """Tests if municipality is a binary file"""

    result = fetch_municipality()

    assert isinstance(result.content, bytes)


def test_fetch_municipality_dump(output_dir: Path) -> None:
    """Saves the downloaded municipality file to tests/output/municipality.xlsx for local inspection"""

    result = fetch_municipality()

    output_file = output_dir / "municipality.xlsx"
    output_file.write_bytes(result.content)

    assert output_file.stat().st_size > 0
