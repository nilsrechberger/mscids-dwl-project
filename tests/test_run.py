"""Test file for storage.py and run.py"""

import json

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.run import handler, run
from src.storage import build_key, write_raw


def test_build_key() -> None:
    """Checks the partitioned key layout"""
    now = datetime(2026, 10, 2, 10, 15, 30, tzinfo=timezone.utc)

    assert build_key("weather", "json", now) == "raw/weather/dt=2026-10-02/101530.json"


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
        ("transport", "fetch_locations", {"a": 1}, "json"),
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
