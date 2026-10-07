"""Test file for gtfs_rt.py"""

import json
from pathlib import Path

from src.loaders.gtfs_rt import fetch_gtfs_rt


def test_fetch_gtfs_rt() -> None:
    """Checks if gtfs_rf data is a dict"""

    result = fetch_gtfs_rt()

    assert isinstance(result, dict)


def test_fetch_gtfs_rt_dump(output_dir: Path) -> None:
    """Saves the fetched gtfs_rt data to tests/output/gtfs_rt.json for local inspection"""

    result = fetch_gtfs_rt()

    output_file = output_dir / "gtfs_rt.json"
    output_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    assert output_file.exists()
