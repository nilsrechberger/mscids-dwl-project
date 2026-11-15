"""Test file for storage.py and run.py"""

import json

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.run import BatchResult, handler, run, run_batch
from src.storage import build_key, read_latest_raw, write_raw


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
            "src.run.fetch_all_locations",
            side_effect=lambda chunk: {n: {} for n in chunk},
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
        "src.run.fetch_all_locations", return_value={"A": {}}
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

    assert out == {"uri": "s3://b/k", "next_batch": 4}
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
