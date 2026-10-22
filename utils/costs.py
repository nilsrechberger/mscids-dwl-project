"""Approx monthly cost model: Lambda, S3 (AWS eu-central-1, arm64) and BigQuery storage

Sizes are measured from test/output.
Free tiers are ignored.
"""

from dataclasses import dataclass

DAYS = 30
STATIONS = 5

LAMBDA_PER_GB_S = 0.0000133
LAMBDA_PER_REQUEST = 0.20 / 1e6
S3_PER_GB = 0.0245
S3_PER_PUT = 0.0054 / 1000
BQ_PER_GB = 0.02


@dataclass(frozen=True)
class Source:
    """Load profile of one data source"""

    runs_per_day: int
    seconds: float  # duration per run
    mem_gb: float  # Lambda memory
    mb: float  # file size written to S3 per run


SOURCES = {
    "gtfs_rt": Source(24, 20, 1.0, 57),  # hourly, full snapshot
    "municipality": Source(1, 5, 0.5, 0.09),  # daily
    "transport": Source(24 * STATIONS, 2, 0.5, 0.002),  # hourly per station
    "weather": Source(24 * STATIONS, 2, 0.5, 0.014),  # hourly per station
}

RUNS = sum(s.runs_per_day for s in SOURCES.values()) * DAYS
GB_S = sum(s.runs_per_day * DAYS * s.seconds * s.mem_gb for s in SOURCES.values())
GB_PER_MONTH = sum(s.runs_per_day * DAYS * s.mb for s in SOURCES.values()) / 1024

LAMBDA = GB_S * LAMBDA_PER_GB_S + RUNS * LAMBDA_PER_REQUEST


def s3(month: int) -> float:
    """Returns the S3 cost in USD for the given month, storage accumulates"""
    return GB_PER_MONTH * month * S3_PER_GB + RUNS * S3_PER_PUT


def dwh(month: int) -> float:
    """Returns the BigQuery cost in USD for the given month (upper bound: all raw data)"""
    return GB_PER_MONTH * month * BQ_PER_GB
