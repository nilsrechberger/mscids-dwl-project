"""Test file for municipality.py"""

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from openpyxl import Workbook

from src.loaders.municipality import fetch_municipality, parse_municipality_names


def test_fetch_municipality() -> None:
    """Returns the raw response with the binary content"""
    session = MagicMock()
    session.post.return_value = MagicMock(content=b"xlsx-bytes")
    with patch("src.loaders.municipality.get_session", return_value=session), patch(
        "src.loaders.municipality.config.MUNICIPALITY_XLSX", "http://bfs"
    ):
        result = fetch_municipality()

    assert result.content == b"xlsx-bytes"


def test_fetch_municipality_error() -> None:
    """Re-raises HTTP errors"""
    session = MagicMock()
    session.post.return_value.raise_for_status.side_effect = (
        requests.exceptions.HTTPError("500")
    )
    with patch("src.loaders.municipality.get_session", return_value=session):
        with pytest.raises(requests.exceptions.HTTPError):
            fetch_municipality()


@pytest.mark.network
def test_fetch_municipality_dump(output_dir: Path) -> None:
    """Saves the downloaded municipality file to tests/output/municipality.xlsx for local inspection"""

    result = fetch_municipality()

    output_file = output_dir / "municipality.xlsx"
    output_file.write_bytes(result.content)

    assert output_file.stat().st_size > 0


def test_parse_municipality_names() -> None:
    """Returns unique municipality names in file order"""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Daten"
    ws.append(["Hist.-Nummer", "Kanton", "Gemeindename"])
    ws.append([1, "BE", "Bern"])
    ws.append([2, "BS", "Basel"])
    ws.append([3, "BE", "Bern"])
    buffer = BytesIO()
    wb.save(buffer)

    assert parse_municipality_names(buffer.getvalue()) == ["Bern", "Basel"]
