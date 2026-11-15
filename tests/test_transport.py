"""Test file for transport.py"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.loaders.transport import fetch_all_locations, fetch_locations


def test_fetch_locations() -> None:
    """Returns the JSON body and passes the query"""
    session = MagicMock()
    get = session.get
    get.return_value.json.return_value = {"stations": []}
    with patch("src.loaders.transport.get_session", return_value=session), patch(
        "src.loaders.transport.config.TRANSPORT_API_ENDPOINT", "http://api"
    ):
        result = fetch_locations(query="Bern")

    assert result == {"stations": []}
    assert get.call_args.args[0] == "http://api/locations"
    assert get.call_args.kwargs["params"] == {"query": "Bern"}


def test_fetch_locations_error() -> None:
    """Re-raises request errors"""
    session = MagicMock()
    session.get.side_effect = requests.exceptions.Timeout("slow")
    with patch("src.loaders.transport.get_session", return_value=session):
        with pytest.raises(requests.exceptions.Timeout):
            fetch_locations()


def test_fetch_all_locations() -> None:
    """Queries every municipality and keys the results by name"""
    session = MagicMock()
    session.get.return_value.json.side_effect = [{"n": 1}, {"n": 2}]
    with patch("src.loaders.transport.get_session", return_value=session), patch(
        "src.loaders.transport.config.TRANSPORT_API_ENDPOINT", "http://api"
    ):
        result = fetch_all_locations(["Bern", "Basel"])

    assert result == {"Bern": {"n": 1}, "Basel": {"n": 2}}
    queries = [c.kwargs["params"]["query"] for c in session.get.call_args_list]
    assert queries == ["Bern", "Basel"]


def test_fetch_all_locations_skips_failures() -> None:
    """One failing municipality does not abort the run"""
    session = MagicMock()
    ok = MagicMock()
    ok.json.return_value = {"n": 1}
    session.get.side_effect = [requests.exceptions.Timeout("slow"), ok]
    with patch("src.loaders.transport.get_session", return_value=session):
        assert fetch_all_locations(["Bern", "Basel"]) == {"Basel": {"n": 1}}


def test_fetch_all_locations_all_fail() -> None:
    """Raises if no municipality could be fetched"""
    session = MagicMock()
    session.get.side_effect = requests.exceptions.Timeout("slow")
    with patch("src.loaders.transport.get_session", return_value=session):
        with pytest.raises(requests.exceptions.Timeout):
            fetch_all_locations(["Bern"])


@pytest.mark.network
def test_fetch_locations_dump(output_dir: Path) -> None:
    """Saves the fetched transport data to tests/output/transport.json for local inspection"""

    result = fetch_locations(query="Bern")

    output_file = output_dir / "transport.json"
    output_file.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    assert output_file.exists()
