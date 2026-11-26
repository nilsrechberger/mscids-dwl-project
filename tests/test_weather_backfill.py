"""Tests for the monthly municipality-weather backfill."""

import json
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.run import handler, run_batch
from src.runs import validate_run_context
from src.weather_backfill import month_ranges, plan_weather_backfill

OPTIONS = {"since": "2025-08-15", "until": "2025-10-10", "point_snapshot": "points-v1"}


def test_month_ranges_clip_both_ends() -> None:
    assert month_ranges(date(2025, 8, 15), date(2025, 10, 10)) == [
        (date(2025, 8, 15), date(2025, 8, 31)),
        (date(2025, 9, 1), date(2025, 9, 30)),
        (date(2025, 10, 1), date(2025, 10, 10)),
    ]
    assert month_ranges(date(2024, 2, 1), date(2024, 2, 29)) == [
        (date(2024, 2, 1), date(2024, 2, 29))
    ]
    with pytest.raises(ValueError):
        month_ranges(date(2025, 9, 1), date(2025, 8, 1))


def s3_with_manifests(manifests: dict[str, dict[str, Any]]) -> MagicMock:
    client = MagicMock()

    def list_objects(Bucket: str, Prefix: str, MaxKeys: int) -> dict:
        return {"Contents": [{"Key": Prefix}]} if Prefix in manifests else {}

    def get_object(Bucket: str, Key: str) -> dict:
        body = MagicMock()
        body.read.return_value = json.dumps(manifests[Key]).encode()
        return {"Body": body}

    client.list_objects_v2.side_effect = list_objects
    client.get_object.side_effect = get_object
    return client


def plan(manifests: dict[str, dict[str, Any]], **extra: Any) -> dict[str, Any]:
    with patch(
        "src.weather_backfill.boto3.client", return_value=s3_with_manifests(manifests)
    ), patch("src.weather_backfill.config.S3_BUCKET", "b"):
        return plan_weather_backfill({**OPTIONS, **extra}, "exec-1")


def test_plan_lists_months_with_waits() -> None:
    result = plan({}, interval_hours=1)

    items = result["items"]
    assert [(i["observation_date"], i["end_date"]) for i in items] == [
        ("2025-08-15", "2025-08-31"),
        ("2025-09-01", "2025-09-30"),
        ("2025-10-01", "2025-10-10"),
    ]
    assert [i["wait_seconds"] for i in items] == [0, 3600, 3600]
    assert items[0]["run_id"] == "municipality-weather-2025-08-15-2025-08-31-points-v1"
    assert items[0]["execution_id"] == "exec-1"
    assert items[0]["batch"] == 0
    assert result["already_loaded"] == []


def test_plan_skips_completed_months_only() -> None:
    prefix = "raw/municipality_weather"
    aug = "municipality-weather-2025-08-15-2025-08-31-points-v1"
    sep = "municipality-weather-2025-09-01-2025-09-30-points-v1"
    result = plan(
        {
            f"{prefix}/dt=2025-08-15/run={aug}/manifest.json": {"status": "completed"},
            f"{prefix}/dt=2025-09-01/run={sep}/manifest.json": {"status": "partial"},
        }
    )

    assert result["already_loaded"] == [aug]
    assert [i["run_id"] for i in result["items"]][0] == sep
    # the first remaining month starts without waiting
    assert result["items"][0]["wait_seconds"] == 0
    assert result["items"][1]["wait_seconds"] == 86400


def test_plan_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="point_snapshot"):
        plan_weather_backfill({"since": "2025-08-01", "until": "2025-08-31"}, "e")
    with pytest.raises(ValueError, match="past"):
        plan_weather_backfill({**OPTIONS, "until": date.today().isoformat()}, "e")
    with pytest.raises(ValueError, match="run_id"):
        plan_weather_backfill({**OPTIONS, "point_snapshot": "x" * 40}, "e")


def test_batch_passes_end_date_and_records_it() -> None:
    payload = {"request": {"points": [{"gdenr": "1"}]}, "response": []}
    fetch = MagicMock(return_value=(payload, 1, ()))
    with patch.dict("src.run.BATCHED_LOADERS", {"municipality_weather": fetch}), patch(
        "src.run.write_raw", return_value="s3://b/k"
    ), patch("src.run.write_run_manifest") as manifest:
        run_batch(
            "municipality_weather",
            0,
            50,
            run_id="r",
            observation_date="2025-08-01",
            end_date="2025-08-31",
        )

    fetch.assert_called_once_with(0, 50, "2025-08-01", "2025-08-31")
    assert manifest.call_args_list[0].args[2]["end_date"] == "2025-08-31"


def test_weather_fetcher_uses_date_range() -> None:
    points = [{"gdenr": "1", "gdename": "A", "latitude": "47", "longitude": "8"}]
    with patch("src.run.load_weather_points", return_value=points), patch(
        "src.run.fetch_batch", return_value={}
    ) as fetch:
        from src.run import _fetch_municipality_weather_batch

        _fetch_municipality_weather_batch(0, 50, "2025-08-01", "2025-08-31")
        _fetch_municipality_weather_batch(0, 50, "2026-11-20")

    assert fetch.call_args_list[0].args[1:] == ("2025-08-01", "2025-08-31")
    assert fetch.call_args_list[1].args[1:] == ("2026-11-20", "2026-11-20")


def test_end_date_validation() -> None:
    base = {
        "run_id": "r",
        "observation_date": "2025-08-01",
        "execution_id": "e",
        "point_snapshot": "points-v1",
    }
    validate_run_context({**base, "end_date": "2025-08-31"}, "municipality_weather")
    with pytest.raises(ValueError, match="before"):
        validate_run_context({**base, "end_date": "2025-07-31"}, "municipality_weather")
    with pytest.raises(ValueError, match="only supported"):
        validate_run_context({**base, "end_date": "2025-08-31"}, "transport")


def test_handler_routes_plan_and_finalize_keeps_end_date() -> None:
    with patch("src.run.plan_weather_backfill", return_value={"items": []}) as p:
        handler(
            {"action": "plan_weather_backfill", "input": OPTIONS, "execution_id": "e"},
            None,
        )
    p.assert_called_once_with(OPTIONS, "e")

    with patch("src.run.finalize_run", return_value={}) as finalize:
        handler(
            {
                "action": "finalize",
                "source": "municipality_weather",
                "run_id": "r",
                "observation_date": "2025-08-01",
                "end_date": "2025-08-31",
                "execution_id": "e",
                "point_snapshot": "points-v1",
            },
            None,
        )
    assert finalize.call_args.kwargs["metadata"]["end_date"] == "2025-08-31"
