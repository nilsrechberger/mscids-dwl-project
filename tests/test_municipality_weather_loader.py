"""Tests for the production municipality weather loader contract."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.loaders.municipality_weather import (
    build_url,
    fetch_batch,
    load_weather_points,
)

POINTS = [
    {"gdenr": "1", "gdename": "Aeugst", "latitude": "47.27", "longitude": "8.48"},
    {"gdenr": "2", "gdename": "Obfelden", "latitude": "47.26", "longitude": "8.42"},
]


def test_load_weather_points_requires_contract(tmp_path: Path) -> None:
    points = tmp_path / "points.csv"
    points.write_text(
        "gdenr,gdename,latitude,longitude\n1,Aeugst,47.27,8.48\n",
        encoding="utf-8",
    )

    result = load_weather_points(points)
    assert result[0]["gdenr"] == "1"


def test_load_weather_points_rejects_missing_columns(tmp_path: Path) -> None:
    points = tmp_path / "points.csv"
    points.write_text("gdenr,gdename\n1,Aeugst\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing columns"):
        load_weather_points(points)


def test_build_url_contains_all_locations_and_variables() -> None:
    with patch(
        "src.loaders.municipality_weather.config.MUNICIPALITY_WEATHER_API_ENDPOINT",
        "https://example.test/archive",
    ):
        url = build_url(POINTS, "2026-11-15", "2026-11-15")

    assert "latitude=47.27%2C47.26" in url
    assert "longitude=8.48%2C8.42" in url
    assert "start_date=2026-11-15" in url
    assert "weather_code" in url


def test_fetch_batch_preserves_request_metadata() -> None:
    session = MagicMock()
    session.get.return_value.json.return_value = [
        {"hourly": {"time": []}},
        {"hourly": {"time": []}},
    ]
    with patch(
        "src.loaders.municipality_weather.get_session", return_value=session
    ), patch(
        "src.loaders.municipality_weather.config.MUNICIPALITY_WEATHER_API_ENDPOINT",
        "https://example.test/archive",
    ):
        result = fetch_batch(POINTS, "2026-11-15", "2026-11-15")

    assert result["request"]["points"] == POINTS
    assert len(result["response"]) == 2
    session.get.assert_called_once()


def test_fetch_batch_rejects_partial_api_response() -> None:
    session = MagicMock()
    session.get.return_value.json.return_value = [{"hourly": {"time": []}}]
    with patch(
        "src.loaders.municipality_weather.get_session", return_value=session
    ), patch(
        "src.loaders.municipality_weather.config.MUNICIPALITY_WEATHER_API_ENDPOINT",
        "https://example.test/archive",
    ):
        with pytest.raises(ValueError, match="Expected 2 weather responses"):
            fetch_batch(POINTS, "2026-11-15", "2026-11-15")
