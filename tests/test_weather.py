"""Test file for weather.py"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.loaders.weather import CANTONS, fetch_weather


def test_fetch_weather() -> None:
    """Requests temperature and rain for all cantons and keys results by code"""
    session = MagicMock()
    get = session.get
    get.return_value.json.return_value = [{"i": i} for i in range(len(CANTONS))]
    with patch("src.loaders.weather.get_session", return_value=session), patch(
        "src.loaders.weather.config.WEATHER_API_ENDPOINT", "http://api"
    ):
        result = fetch_weather()

    assert list(result) == list(CANTONS)
    assert result["AG"] == {"i": 0}
    assert len(CANTONS) == 26
    params = get.call_args.kwargs["params"]
    assert get.call_args.args[0] == "http://api"
    assert params["hourly"] == "temperature_2m,rain"
    assert len(params["latitude"].split(",")) == 26
    assert len(params["longitude"].split(",")) == 26


def test_fetch_weather_unexpected_count() -> None:
    """Fails if Open-Meteo returns fewer locations than requested"""
    session = MagicMock()
    session.get.return_value.json.return_value = [{}]
    with patch("src.loaders.weather.get_session", return_value=session):
        with pytest.raises(ValueError):
            fetch_weather()


def test_fetch_weather_error() -> None:
    """Re-raises request errors"""
    session = MagicMock()
    session.get.side_effect = requests.exceptions.ConnectionError("boom")
    with patch("src.loaders.weather.get_session", return_value=session):
        with pytest.raises(requests.exceptions.ConnectionError):
            fetch_weather()


@pytest.mark.network
def test_fetch_weather_dump(output_dir: Path) -> None:
    """Saves the weather data to tests/output/weather.json for local inspection"""

    result = fetch_weather()

    output_file = output_dir / "weather.json"
    output_file.write_text(json.dumps(result, indent=2), encoding="utf-8")

    assert result["ZH"]["hourly"]["rain"]
