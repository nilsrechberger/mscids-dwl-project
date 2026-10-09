"""Test file for municipality.py"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.loaders.municipality import fetch_municipality


def test_fetch_municipality() -> None:
    """Returns the raw response with the binary content"""
    response = MagicMock(content=b"xlsx-bytes")
    with patch("src.loaders.municipality.requests.post", return_value=response), patch(
        "src.loaders.municipality.config.MUNICIPALITY_XLSX", "http://bfs"
    ):
        result = fetch_municipality()

    assert result.content == b"xlsx-bytes"


def test_fetch_municipality_error() -> None:
    """Re-raises HTTP errors"""
    response = MagicMock()
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
    with patch("src.loaders.municipality.requests.post", return_value=response):
        with pytest.raises(requests.exceptions.HTTPError):
            fetch_municipality()


@pytest.mark.network
def test_fetch_municipality_dump(output_dir: Path) -> None:
    """Saves the downloaded municipality file to tests/output/municipality.xlsx for local inspection"""

    result = fetch_municipality()

    output_file = output_dir / "municipality.xlsx"
    output_file.write_bytes(result.content)

    assert output_file.stat().st_size > 0
