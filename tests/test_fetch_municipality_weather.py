"""Tests for the local Open-Meteo municipality loader."""

from scripts.fetch_municipality_weather import build_url, normalize_response


def test_build_url_contains_batch_and_dates() -> None:
    points = [
        {"gdenr": "261", "gdename": "Zürich", "latitude": "47.37", "longitude": "8.54"}
    ]
    url = build_url("https://example.test/weather", points, "2026-11-10", "2026-11-10")
    assert "latitude=47.37" in url
    assert "longitude=8.54" in url
    assert "start_date=2026-11-10" in url


def test_normalize_multi_location_response() -> None:
    points = [
        {"gdenr": "261", "gdename": "Zürich", "latitude": "47.37", "longitude": "8.54"},
        {"gdenr": "351", "gdename": "Bern", "latitude": "46.95", "longitude": "7.44"},
    ]
    response = [
        {
            "hourly": {
                "time": ["2026-11-10T00:00", "2026-11-10T01:00"],
                "temperature_2m": [5, 4],
                "precipitation": [0, 1],
                "rain": [0, 1],
                "snowfall": [0, 0],
                "wind_speed_10m": [2, 3],
                "weather_code": [1, 2],
            }
        },
        {
            "hourly": {
                "time": ["2026-11-10T00:00"],
                "temperature_2m": [3],
                "precipitation": [0],
                "rain": [0],
                "snowfall": [0],
                "wind_speed_10m": [1],
                "weather_code": [0],
            }
        },
    ]
    rows = normalize_response(response, points)
    assert len(rows) == 3
    assert rows[0]["gdenr"] == "261"
    assert rows[-1]["gdenr"] == "351"
    assert rows[0]["temperature_2m"] == "5"
