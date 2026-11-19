"""Tests for run context and manifest finalization."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.runs import finalize_run, require_completed_run, validate_run_context


def test_validate_municipality_weather_context() -> None:
    validate_run_context(
        {
            "run_id": "weather-2026-11-15-v1",
            "observation_date": "2026-11-15",
            "point_snapshot": "points-2026-11-16-v1",
            "execution_id": "execution-1",
        },
        "municipality_weather",
    )


def test_validate_context_requires_weather_snapshot() -> None:
    with pytest.raises(ValueError, match="point_snapshot"):
        validate_run_context(
            {
                "run_id": "weather-1",
                "observation_date": "2026-11-15",
                "execution_id": "execution-1",
            },
            "municipality_weather",
        )


def test_finalize_run_writes_completed_summary() -> None:
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {
            "Contents": [
                {
                    "Key": "raw/municipality_weather/dt=2026-11-15/run=r/manifest_part0000.json"
                },
                {
                    "Key": "raw/municipality_weather/dt=2026-11-15/run=r/manifest_part0001.json"
                },
            ]
        }
    ]
    client.get_object.side_effect = [
        {
            "Body": MagicMock(
                read=lambda: json.dumps(
                    {"batch": 0, "batch_count": 2, "failed_municipalities": []}
                ).encode()
            )
        },
        {
            "Body": MagicMock(
                read=lambda: json.dumps(
                    {"batch": 1, "batch_count": 2, "failed_municipalities": []}
                ).encode()
            )
        },
    ]
    with patch("src.runs.boto3.client", return_value=client), patch(
        "src.runs.config.S3_BUCKET", "bucket"
    ), patch("src.runs.write_run_manifest") as write:
        summary = finalize_run("municipality_weather", "r", "2026-11-15")

    assert summary["status"] == "completed"
    assert summary["completed_batches"] == 2
    assert summary["api_requests"] == 2
    write.assert_called_once()
    assert write.call_args.kwargs["now"].date().isoformat() == "2026-11-15"


def test_require_completed_run_rejects_partial_manifest() -> None:
    client = MagicMock()
    client.get_object.return_value = {
        "Body": MagicMock(read=lambda: b'{"status": "partial"}')
    }
    with patch("src.runs.boto3.client", return_value=client), patch(
        "src.runs.config.S3_BUCKET", "bucket"
    ), pytest.raises(RuntimeError, match="not complete"):
        require_completed_run("municipality_weather", "r", "2026-11-15")
