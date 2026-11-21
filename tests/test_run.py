"""Test file for storage.py and run.py"""

import json

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.run import BatchResult, handler, run, run_batch
from src.loaders.transport import LocationFetchResult
from src.storage import (
    build_key,
    read_latest_raw,
    write_raw,
    write_raw_stream,
    write_run_manifest,
)


def test_build_key() -> None:
    """Checks the partitioned key layout"""
    now = datetime(2026, 10, 2, 10, 15, 30, tzinfo=timezone.utc)

    assert build_key("weather", "json", now) == "raw/weather/dt=2026-10-02/101530.json"


def test_build_key_with_part() -> None:
    """Batches get a part suffix so they never overwrite each other"""
    now = datetime(2026, 10, 2, 10, 15, 30, tzinfo=timezone.utc)

    assert (
        build_key("transport", "json", now, part=3)
        == "raw/transport/dt=2026-10-02/101530_part0003.json"
    )


def test_build_key_with_run_id_is_deterministic() -> None:
    """Run IDs create stable keys independent of invocation time."""
    first = build_key(
        "transport",
        "json",
        datetime(2026, 10, 2, 10, 15, 30, tzinfo=timezone.utc),
        part=3,
        run_id="2026-10-02-run-1",
    )
    second = build_key(
        "transport",
        "json",
        datetime(2026, 10, 2, 18, 45, 0, tzinfo=timezone.utc),
        part=3,
        run_id="2026-10-02-run-1",
    )
    assert first == second
    assert first == "raw/transport/dt=2026-10-02/run=2026-10-02-run-1/part0003.json"


def test_write_run_manifest() -> None:
    """Manifest metadata is written below the deterministic run prefix."""
    client = MagicMock()
    now = datetime(2026, 10, 2, 10, 15, 30, tzinfo=timezone.utc)
    with patch("src.storage.boto3.client", return_value=client), patch(
        "src.storage.config.S3_BUCKET", "my-bucket"
    ):
        uri = write_run_manifest("transport", "run-1", {"failed": 2}, now=now)

    assert uri == "s3://my-bucket/raw/transport/dt=2026-10-02/run=run-1/manifest.json"
    kwargs = client.put_object.call_args.kwargs
    assert kwargs["ContentType"] == "application/json"
    assert json.loads(kwargs["Body"])["failed"] == 2


def test_write_batch_manifest_uses_part_key() -> None:
    """Each completed batch gets its own deterministic manifest."""
    client = MagicMock()
    now = datetime(2026, 10, 2, 10, 15, 30, tzinfo=timezone.utc)
    with patch("src.storage.boto3.client", return_value=client), patch(
        "src.storage.config.S3_BUCKET", "my-bucket"
    ):
        uri = write_run_manifest("transport", "run-1", {"batch": 3}, now=now, part=3)

    assert uri.endswith("/manifest_part0003.json")


def test_write_raw() -> None:
    """Checks that the object is put into the configured bucket"""
    client = MagicMock()
    with patch("src.storage.boto3.client", return_value=client), patch(
        "src.storage.config.S3_BUCKET", "my-bucket"
    ):
        uri = write_raw("transport", b"{}", "json")

    kwargs = client.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "my-bucket"
    assert kwargs["Body"] == b"{}"
    assert uri == f"s3://my-bucket/{kwargs['Key']}"


def test_write_raw_stream() -> None:
    """Uploads a stream without passing bytes to put_object"""
    client = MagicMock()
    stream = MagicMock()
    with patch("src.storage.boto3.client", return_value=client), patch(
        "src.storage.config.S3_BUCKET", "my-bucket"
    ):
        uri = write_raw_stream("istdaten_v2", stream, "csv")

    kwargs = client.upload_fileobj.call_args.args
    assert kwargs[0] is stream
    assert kwargs[1] == "my-bucket"
    assert uri == f"s3://my-bucket/{kwargs[2]}"


def test_read_latest_raw() -> None:
    """Reads the object with the largest (newest) key"""
    client = MagicMock()
    paginator = client.get_paginator.return_value
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "raw/municipality/dt=2026-01-01/100000.xlsx"}]},
        {"Contents": [{"Key": "raw/municipality/dt=2026-02-01/090000.xlsx"}]},
    ]
    client.get_object.return_value = {"Body": MagicMock(read=lambda: b"new")}
    with patch("src.storage.boto3.client", return_value=client), patch(
        "src.storage.config.S3_BUCKET", "my-bucket"
    ):
        assert read_latest_raw("municipality") == b"new"

    assert (
        client.get_object.call_args.kwargs["Key"]
        == "raw/municipality/dt=2026-02-01/090000.xlsx"
    )


def test_read_latest_raw_empty() -> None:
    """Returns None if the source has no files"""
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{}]
    with patch("src.storage.boto3.client", return_value=client), patch(
        "src.storage.config.S3_BUCKET", "my-bucket"
    ):
        assert read_latest_raw("municipality") is None


def test_write_raw_without_bucket() -> None:
    """Fails fast if no bucket is configured"""
    with patch("src.storage.config.S3_BUCKET", None):
        with pytest.raises(RuntimeError):
            write_raw("transport", b"{}", "json")


def test_run_unknown_source() -> None:
    """Rejects unknown source names"""
    with pytest.raises(ValueError):
        run("nope")


def test_run_istdaten_v2_loads_latest_day() -> None:
    """Local runs load the newest published Ist-Daten v2 day"""
    with patch("src.run.load_latest", return_value={"uri": "s3://b/k"}) as load:
        assert run("istdaten_v2") == "s3://b/k"
    load.assert_called_once_with()


def test_handler_istdaten_v2_loads_requested_day() -> None:
    with patch(
        "src.run.load_operating_day", return_value={"status": "completed"}
    ) as load:
        assert handler(
            {"source": "istdaten_v2", "operating_day": "2026-11-20"}, None
        ) == {"status": "completed"}
    load.assert_called_once_with("2026-11-20")


def test_handler_istdaten_v2_without_day_loads_latest() -> None:
    with patch("src.run.load_latest", return_value={"status": "skipped"}):
        assert handler({"source": "istdaten_v2"}, None) == {"status": "skipped"}


def test_handler_istdaten_v2_rejects_invalid_day() -> None:
    with pytest.raises(ValueError):
        handler({"source": "istdaten_v2", "operating_day": "20.11.2026"}, None)


def test_handler_plan_istdaten_sync_passes_options() -> None:
    with patch("src.run.plan_sync", return_value={"operating_days": []}) as plan:
        result = handler(
            {
                "action": "plan_istdaten_sync",
                "input": {"since": "2026-10-01", "max_days": "5"},
            },
            None,
        )
    assert result == {"operating_days": []}
    plan.assert_called_once_with(since="2026-10-01", max_days=5)


def test_handler_plan_istdaten_sync_defaults() -> None:
    with patch("src.run.plan_sync", return_value={}) as plan:
        handler({"action": "plan_istdaten_sync", "input": {}}, None)
    plan.assert_called_once_with(since=None, max_days=None)


@pytest.mark.parametrize(
    "source, loader, payload, extension",
    [
        ("weather", "fetch_weather", {"a": 1}, "json"),
        ("gtfs_rt", "fetch_gtfs_rt", {"a": 1}, "json"),
    ],
)
def test_run_json_sources(
    source: str, loader: str, payload: dict, extension: str
) -> None:
    """JSON sources are serialised unchanged and written under their source name"""
    with patch(f"src.run.{loader}", return_value=payload), patch(
        "src.run.write_raw", return_value="s3://b/k"
    ) as write:
        assert run(source) == "s3://b/k"

    write.assert_called_once_with(source, json.dumps(payload).encode(), extension)


def _transport_patches(names: list[str]):  # type: ignore[no-untyped-def]
    return (
        patch("src.run.read_latest_raw", return_value=b"x"),
        patch("src.run.parse_municipality_names", return_value=names),
        patch(
            "src.run.fetch_all_locations_with_status",
            side_effect=lambda chunk: LocationFetchResult(
                results={n: {} for n in chunk}, failed=()
            ),
        ),
    )


def test_run_batch_slices_municipalities() -> None:
    """Each batch fetches its own slice and points to the next one"""
    p1, p2, p3 = _transport_patches(["A", "B", "C", "D", "E"])
    with p1, p2, p3 as fetch, patch("src.run.write_raw", return_value="s3://b/k") as w:
        first = run_batch("transport", 0, 2)
        last = run_batch("transport", 2, 2)

    assert [c.args[0] for c in fetch.call_args_list] == [["A", "B"], ["E"]]
    assert first.next_batch == 1
    assert last.next_batch is None
    assert w.call_args_list[0].kwargs["part"] == 0
    assert w.call_args_list[1].kwargs["part"] == 2
    assert w.call_args_list[1].args[1] == json.dumps({"E": {}}).encode()


def test_weather_batch_receives_observation_date() -> None:
    """Scheduled weather runs pass their derived date to the loader."""
    payload = {"request": {"points": [{"gdenr": "1"}]}, "response": []}
    with patch(
        "src.run._fetch_municipality_weather_batch",
        return_value=(payload, 1, ()),
    ) as fetch, patch("src.run.write_raw", return_value="s3://b/k"), patch(
        "src.run.write_run_manifest"
    ):
        result = run_batch(
            "municipality_weather",
            0,
            50,
            run_id="weather-run",
            observation_date="2026-11-20",
        )

    assert result.next_batch is None
    fetch.assert_called_once_with(0, 50, "2026-11-20")


def test_run_batch_writes_manifests_for_run_id() -> None:
    """A run ID enables deterministic batch and final manifests."""
    p1, p2, p3 = _transport_patches(["A"])
    with p1, p2, p3, patch("src.run.write_raw", return_value="s3://b/k"), patch(
        "src.run.write_run_manifest"
    ) as manifest:
        result = run_batch("transport", 0, 10, run_id="run-1")

    assert result.next_batch is None
    assert manifest.call_count == 2
    assert manifest.call_args_list[0].kwargs["part"] == 0
    assert manifest.call_args_list[1].args[1] == "run-1"


def test_run_batch_out_of_range() -> None:
    """A batch beyond the last one is rejected before anything is written"""
    p1, p2, p3 = _transport_patches(["A", "B"])
    with p1, p2, p3, patch("src.run.write_raw") as w:
        with pytest.raises(ValueError):
            run_batch("transport", 1, 2)
    w.assert_not_called()


def test_transport_downloads_municipalities_if_missing() -> None:
    """Falls back to the BFS download when the data lake has no file yet"""
    with patch("src.run.read_latest_raw", return_value=None), patch(
        "src.run.fetch_municipality", return_value=MagicMock(content=b"xlsx")
    ) as download, patch(
        "src.run.parse_municipality_names", return_value=["A"]
    ) as parse, patch(
        "src.run.fetch_all_locations_with_status",
        return_value=LocationFetchResult(results={"A": {}}, failed=()),
    ), patch(
        "src.run.write_raw", return_value="s3://b/k"
    ):
        run_batch("transport", 0, 10)

    download.assert_called_once()
    parse.assert_called_once_with(b"xlsx")


def test_run_batch_not_batched() -> None:
    """Only batched sources can be run per batch"""
    with pytest.raises(ValueError):
        run_batch("weather")


def test_run_transport_all_batches() -> None:
    """run() walks through all batches for local runs"""
    p1, p2, p3 = _transport_patches(["A", "B", "C"])
    with p1, p2, p3, patch("src.run.config.TRANSPORT_BATCH_SIZE", 2), patch(
        "src.run.write_raw", return_value="s3://b/k"
    ) as w:
        run("transport")

    assert w.call_count == 2


def test_handler_batched() -> None:
    """The handler reports the next batch so a caller can loop"""
    with patch("src.run.run_batch", return_value=BatchResult("s3://b/k", 4)) as rb:
        out = handler({"source": "transport", "batch": 3}, None)

    assert out == {
        "uri": "s3://b/k",
        "next_batch": 4,
        "failed_municipalities": [],
    }
    rb.assert_called_once_with("transport", 3, None)


def test_run_municipality() -> None:
    """The XLSX bytes are written as-is"""
    with patch(
        "src.run.fetch_municipality", return_value=MagicMock(content=b"xlsx")
    ), patch("src.run.write_raw", return_value="s3://b/k") as write:
        run("municipality")

    write.assert_called_once_with("municipality", b"xlsx", "xlsx")


def test_handler() -> None:
    """The Lambda handler returns the S3 URI for the requested source"""
    with patch("src.run.run", return_value="s3://b/k") as run_mock:
        assert handler({"source": "weather"}, None) == {"uri": "s3://b/k"}

    run_mock.assert_called_once_with("weather")


def test_handler_prepares_previous_day_weather_run() -> None:
    """Daily preparation selects the completed UTC day and a stable run ID."""
    result = handler(
        {
            "action": "prepare_daily",
            "source": "municipality_weather",
            "execution_id": "daily-execution",
            "execution_start_date": "2026-11-20",
            "point_snapshot": "points-v1",
            "batch": 0,
            "batch_size": 50,
        },
        None,
    )

    assert result == {
        "source": "municipality_weather",
        "run_id": "municipality-weather-2026-11-19-points-v1",
        "execution_id": "daily-execution",
        "observation_date": "2026-11-19",
        "point_snapshot": "points-v1",
        "batch": 0,
        "batch_size": 50,
    }


def test_handler_finalizes_manifest() -> None:
    """The orchestration action delegates final manifest creation."""
    summary = {"status": "completed", "source": "transport"}
    with patch("src.run.finalize_run", return_value=summary) as finalize:
        result = handler(
            {
                "action": "finalize",
                "source": "transport",
                "run_id": "run-1",
                "observation_date": "2026-10-02",
                "execution_id": "execution-1",
            },
            None,
        )

    assert result == summary
    finalize.assert_called_once_with(
        "transport",
        "run-1",
        "2026-10-02",
        metadata={"execution_id": "execution-1"},
    )
