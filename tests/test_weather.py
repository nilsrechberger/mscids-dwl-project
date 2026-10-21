"""Test file for weather.py"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.loaders.weather import fetch_weather


def test_fetch_weather() -> None:
    """Returns the JSON body and requests hourly temperature"""
    session = MagicMock()
    get = session.get
    get.return_value.json.return_value = {"hourly": {"temperature_2m": [1.0]}}
    with patch("src.loaders.weather.get_session", return_value=session), patch(
        "src.loaders.weather.config.WEATHER_API_ENDPOINT", "http://api"
    ):
        result = fetch_weather()

    assert result == {"hourly": {"temperature_2m": [1.0]}}
    assert get.call_args.args[0] == "http://api"
    assert get.call_args.kwargs["params"]["hourly"] == "temperature_2m"


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

    assert result["hourly"]["temperature_2m"]
