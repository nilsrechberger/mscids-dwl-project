"""Tests for canonical ingestion source contracts."""

import pytest

from src.run import handler
from src.sources import ALL_SOURCES, PRODUCTION_SOURCES, require_source


def test_source_registry_has_stable_primary_sources() -> None:
    assert "istdaten_v2" in PRODUCTION_SOURCES
    assert "municipality" in PRODUCTION_SOURCES
    assert "municipality_weather" in PRODUCTION_SOURCES
    assert "weather" in ALL_SOURCES
    assert require_source("istdaten_v2").kind == "stream"
    assert require_source("istdaten_v2").extension == "csv"
    assert require_source("municipality_weather").kind == "batched"


def test_legacy_sources_are_explicitly_non_production() -> None:
    assert require_source("transport").production is False
    assert require_source("gtfs_rt").production is False
    assert require_source("weather").production is False


def test_unknown_source_has_actionable_error() -> None:
    with pytest.raises(ValueError, match="choose from"):
        require_source("not-a-source")


def test_handler_rejects_missing_source() -> None:
    with pytest.raises(ValueError, match="string 'source'"):
        handler({}, None)
