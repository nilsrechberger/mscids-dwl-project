"""Test file for transport.py"""

import json
from pathlib import Path

from src.loaders.transport import fetch_locations


def test_fetch_location() -> None:
    """Checks if gtfs_rf data is a dict"""

    result = fetch_locations(query="Bern")

    assert isinstance(result, dict)


def test_fetch_location_dump(output_dir: Path) -> None:
    """Saves the fetched transport data to tests/output/transport.json for local inspection"""

    result = fetch_locations(query="Bern")

    output_file = output_dir / "transport.json"
    output_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    assert output_file.exists()
