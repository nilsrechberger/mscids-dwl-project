"""Canonical source contracts used by the ingestion entry point."""

from dataclasses import dataclass
from typing import Literal

LoaderKind = Literal["json", "xlsx", "stream", "batched"]


@dataclass(frozen=True)
class SourceContract:
    """Stable contract for one ingestion source."""

    name: str
    kind: LoaderKind
    extension: str
    production: bool
    description: str


SOURCE_CONTRACTS: dict[str, SourceContract] = {
    "istdaten_v2": SourceContract(
        name="istdaten_v2",
        kind="stream",
        extension="csv",
        production=True,
        description=(
            "Official daily Ist-Daten v2 CSVs, synced from the CKAN catalogue; "
            "older days imported from the monthly ZIP archives"
        ),
    ),
    "service_points": SourceContract(
        name="service_points",
        kind="stream",
        extension="csv",
        production=True,
        description=(
            "atlas service points (full export): stops with SLOID, BPUIC, "
            "coordinates and BFS municipality number per validity period"
        ),
    ),
    "municipality": SourceContract(
        name="municipality",
        kind="xlsx",
        extension="xlsx",
        production=True,
        description="BFS municipality reference workbook",
    ),
    "municipality_weather": SourceContract(
        name="municipality_weather",
        kind="batched",
        extension="json",
        production=True,
        description="Batched Open-Meteo archive responses for municipality points",
    ),
    "weather": SourceContract(
        name="weather",
        kind="json",
        extension="json",
        production=False,
        description="Existing canton-level weather loader; baseline only",
    ),
    "transport": SourceContract(
        name="transport",
        kind="batched",
        extension="json",
        production=False,
        description="Legacy location-search API loader; optional compatibility source",
    ),
    "gtfs_rt": SourceContract(
        name="gtfs_rt",
        kind="json",
        extension="json",
        production=False,
        description="Legacy GTFS-Realtime JSON loader; not the historical primary source",
    ),
}


PRODUCTION_SOURCES = tuple(
    name for name, contract in SOURCE_CONTRACTS.items() if contract.production
)
ALL_SOURCES = tuple(SOURCE_CONTRACTS)


def require_source(source: str) -> SourceContract:
    """Return a source contract or raise a useful configuration error."""
    try:
        return SOURCE_CONTRACTS[source]
    except KeyError as error:
        choices = ", ".join(ALL_SOURCES)
        raise ValueError(f"Unknown source '{source}', choose from {choices}") from error
