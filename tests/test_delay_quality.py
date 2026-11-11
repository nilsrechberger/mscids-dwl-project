"""Tests for Silver-layer delay quality classification."""

from scripts.delay_quality import classify_delay


def test_real_delay_is_usable() -> None:
    result = classify_delay("10.11.2026 08:00", "10.11.2026 08:02:30", "REAL")
    assert result["delay_raw_seconds"] == 150
    assert result["delay_quality"] == "valid"
    assert result["usable_for_real_delay"] is True


def test_forecast_is_valid_but_not_real_delay() -> None:
    result = classify_delay("10.11.2026 08:00", "10.11.2026 08:02", "PROGNOSE")
    assert result["delay_quality"] == "valid"
    assert result["usable_for_real_delay"] is False


def test_missing_time_is_excluded_without_raw_value() -> None:
    result = classify_delay("10.11.2026 08:00", "", "REAL")
    assert result["delay_raw_seconds"] is None
    assert result["delay_quality"] == "missing_time"


def test_unknown_status_is_excluded() -> None:
    result = classify_delay("10.11.2026 08:00", "10.11.2026 08:02", "UNBEKANNT")
    assert result["delay_quality"] == "unknown_status"
    assert result["delay_exclusion_reason"] == "status_not_supported"


def test_cross_day_timestamp_is_excluded() -> None:
    result = classify_delay("10.11.2026 23:59", "11.11.2026 00:01", "REAL")
    assert result["delay_quality"] == "cross_day_or_invalid"
    assert result["delay_exclusion_reason"] == "timestamp_dates_differ"


def test_extreme_delay_is_excluded_but_raw_value_kept() -> None:
    result = classify_delay("10.11.2026 08:00", "10.11.2026 16:01", "REAL")
    assert result["delay_raw_seconds"] == 28860
    assert result["delay_quality"] == "extreme_outlier"
    assert result["usable_for_real_delay"] is False
