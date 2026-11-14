"""Classify raw Ist-Daten delay values without modifying the raw value."""

from __future__ import annotations

from datetime import datetime
from typing import Any

KNOWN_STATUSES = {"REAL", "PROGNOSE", "GESCHAETZT"}
DEFAULT_MAX_ABS_SECONDS = 6 * 60 * 60


def parse_istdaten_time(value: str | None) -> datetime | None:
    """Parse the two timestamp formats found in Ist-Daten v2."""
    if not value:
        return None
    for pattern in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return None


def classify_delay(
    scheduled_value: str | None,
    forecast_value: str | None,
    status_value: str | None,
    max_abs_seconds: int = DEFAULT_MAX_ABS_SECONDS,
) -> dict[str, Any]:
    """Return raw delay, quality class and analytical usability flags."""
    status = (status_value or "").strip().upper()
    scheduled = parse_istdaten_time(scheduled_value)
    forecast = parse_istdaten_time(forecast_value)
    result: dict[str, Any] = {
        "delay_raw_seconds": None,
        "delay_quality": "missing_time",
        "delay_exclusion_reason": "missing_time",
        "usable_for_real_delay": False,
        "status": status or "<NA>",
    }
    if scheduled is None or forecast is None:
        return result
    if status not in KNOWN_STATUSES:
        result["delay_quality"] = "unknown_status"
        result["delay_exclusion_reason"] = "status_not_supported"
        return result
    if scheduled.date() != forecast.date():
        result["delay_quality"] = "cross_day_or_invalid"
        result["delay_exclusion_reason"] = "timestamp_dates_differ"
        return result
    delay = int((forecast - scheduled).total_seconds())
    result["delay_raw_seconds"] = delay
    if abs(delay) > max_abs_seconds:
        result["delay_quality"] = "extreme_outlier"
        result["delay_exclusion_reason"] = "absolute_delay_exceeds_threshold"
        return result
    result["delay_quality"] = "valid"
    result["delay_exclusion_reason"] = ""
    result["usable_for_real_delay"] = status == "REAL"
    return result
