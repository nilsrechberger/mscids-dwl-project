"""Test file for gtfs_rt.py"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.loaders.gtfs_rt import fetch_gtfs_rt


def test_fetch_gtfs_rt() -> None:
    """Returns the JSON body and sends the token as Authorization header"""
    response = MagicMock()
    response.json.return_value = {"header": {}}
    with patch("src.loaders.gtfs_rt.requests.get", return_value=response) as get, patch(
        "src.loaders.gtfs_rt.config.GTFS_RT_API_TOKEN", "secret"
    ), patch("src.loaders.gtfs_rt.config.GTFS_RT_API_ENDPOINT", "http://api"):
        result = fetch_gtfs_rt()

    assert result == {"header": {}}
    assert get.call_args.kwargs["url"] == "http://api?format=JSON"
    assert get.call_args.kwargs["headers"] == {"Authorization": "secret"}


def test_fetch_gtfs_rt_error() -> None:
    """Re-raises request errors"""
    with patch(
        "src.loaders.gtfs_rt.requests.get",
        side_effect=requests.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            fetch_gtfs_rt()


@pytest.mark.network
def test_fetch_gtfs_rt_dump(output_dir: Path) -> None:
    """Saves the fetched gtfs_rt data to tests/output/gtfs_rt.json for local inspection"""

    result = fetch_gtfs_rt()

    output_file = output_dir / "gtfs_rt.json"
    output_file.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    assert output_file.exists()
