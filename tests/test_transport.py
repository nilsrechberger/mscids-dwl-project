"""Test file for transport.py"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.loaders.transport import fetch_locations


def test_fetch_locations() -> None:
    """Returns the JSON body and passes the query"""
    response = MagicMock()
    response.json.return_value = {"stations": []}
    with patch(
        "src.loaders.transport.requests.get", return_value=response
    ) as get, patch(
        "src.loaders.transport.config.TRANSPORT_API_ENDPOINT", "http://api"
    ):
        result = fetch_locations(query="Bern")

    assert result == {"stations": []}
    assert get.call_args.args[0] == "http://api/locations"
    assert get.call_args.kwargs["params"] == {"query": "Bern"}


def test_fetch_locations_error() -> None:
    """Re-raises request errors"""
    with patch(
        "src.loaders.transport.requests.get",
        side_effect=requests.exceptions.Timeout("slow"),
    ):
        with pytest.raises(requests.exceptions.Timeout):
            fetch_locations()


@pytest.mark.network
def test_fetch_locations_dump(output_dir: Path) -> None:
    """Saves the fetched transport data to tests/output/transport.json for local inspection"""

    result = fetch_locations(query="Bern")

    output_file = output_dir / "transport.json"
    output_file.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    assert output_file.exists()
