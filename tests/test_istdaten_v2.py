"""Tests for the Ist-Daten v2 raw loader."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.loaders.istdaten_v2 import fetch_istdaten_v2


def test_fetch_istdaten_v2_streams_csv() -> None:
    response = MagicMock()
    response.raw = MagicMock()
    with patch("src.loaders.istdaten_v2.get_session") as get_session, patch(
        "src.loaders.istdaten_v2.config.ISTDATEN_V2_ENDPOINT",
        "https://data.example/istdaten.csv",
    ):
        get_session.return_value.get.return_value = response
        assert fetch_istdaten_v2() is response

    get_session.return_value.get.assert_called_once_with(
        "https://data.example/istdaten.csv",
        headers={"Accept": "text/csv", "User-Agent": "mscids-dwl-project/1.0"},
        stream=True,
        timeout=(10, 600),
    )
    response.raise_for_status.assert_called_once()
    assert response.raw.decode_content is True


def test_fetch_istdaten_v2_requires_endpoint() -> None:
    with patch("src.loaders.istdaten_v2.config.ISTDATEN_V2_ENDPOINT", None):
        with pytest.raises(RuntimeError):
            fetch_istdaten_v2()


def test_fetch_istdaten_v2_re_raises_request_error() -> None:
    with patch(
        "src.loaders.istdaten_v2.config.ISTDATEN_V2_ENDPOINT", "https://data.example"
    ), patch("src.loaders.istdaten_v2.get_session") as get_session:
        get_session.return_value.get.side_effect = requests.exceptions.Timeout("slow")
        with pytest.raises(requests.exceptions.Timeout):
            fetch_istdaten_v2()
