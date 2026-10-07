"""Test file for weather.py"""

from pathlib import Path

import pandas as pd

from src.config import config
from src.loaders.weather import fetch_weather


def test_fetch_location() -> None:
    """Checks if gtfs_rf data is a dict"""

    assert config.WEATHER_API_ENDPOINT is not None

    result = fetch_weather(url=config.WEATHER_API_ENDPOINT)

    assert isinstance(result, list)


def test_fetch_weather_dump(output_dir: Path) -> None:
    """Saves the hourly weather data to tests/output/weather.csv for local inspection"""

    assert config.WEATHER_API_ENDPOINT is not None

    response = fetch_weather(url=config.WEATHER_API_ENDPOINT)[0]
    hourly = response.Hourly()

    df = pd.DataFrame(
        {
            "date": pd.date_range(
                start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
                end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=hourly.Interval()),
                inclusive="left",
            ),
            "temperature_2m": hourly.Variables(0).ValuesAsNumpy(),
        }
    )

    output_file = output_dir / "weather.csv"
    df.to_csv(output_file, index=False)

    assert not df.empty
