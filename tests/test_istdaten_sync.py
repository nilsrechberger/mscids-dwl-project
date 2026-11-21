"""Tests for the Ist-Daten v2 CKAN sync (planning and loading)."""

import io
import json
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.istdaten_sync import (
    _MeteredStream,
    load_latest,
    load_operating_day,
    plan_sync,
)
from src.loaders.istdaten_v2 import IstdatenResource

CSV = b"\xef\xbb\xbfBETRIEBSTAG;FAHRT_BEZEICHNER\n20.11.2026;1\n"
CSV_MD5 = "0" * 32


def resource(day: str, hash_: str = "a" * 32, size: int | None = None) -> Any:
    return IstdatenResource(
        operating_day=day,
        resource_id=f"id-{day}",
        url=f"https://data.opentransportdata.swiss/r/{day}_istdaten.csv",
        hash=hash_,
        size=size,
        created=None,
        last_modified=None,
    )


def manifest(day: str, fingerprint: str) -> dict[str, str]:
    return {
        "Key": f"raw/istdaten_v2/dt={day}/run=istdaten-v2-{day}-{fingerprint}"
        "/manifest.json"
    }


def s3_listing(*objects: dict[str, str]) -> MagicMock:
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"Contents": list(objects)}
    ]
    return client


def test_plan_lists_missing_and_replaced_days_newest_first() -> None:
    resources = [
        resource("2026-11-18"),
        resource("2026-11-19", hash_="b" * 32),
        resource("2026-11-20"),
    ]
    client = s3_listing(
        manifest("2026-11-18", "a" * 12),
        manifest("2026-11-19", "a" * 12),
        {"Key": "raw/istdaten_v2/dt=2026-11-21/060044.csv"},
    )
    with patch(
        "src.istdaten_sync.list_istdaten_resources", return_value=resources
    ), patch("src.istdaten_sync.boto3.client", return_value=client), patch(
        "src.istdaten_sync.config.S3_BUCKET", "b"
    ):
        plan = plan_sync(today=date(2026, 11, 21))

    assert plan["operating_days"] == ["2026-11-20", "2026-11-19"]
    assert plan["replaced"] == ["2026-11-19"]
    assert plan["latest_available"] == "2026-11-20"
    assert plan["stale"] is False


def test_plan_respects_since_max_days_and_detects_stale_source() -> None:
    resources = [resource(f"2026-11-{day:02d}") for day in range(10, 16)]
    with patch(
        "src.istdaten_sync.list_istdaten_resources", return_value=resources
    ), patch("src.istdaten_sync.boto3.client", return_value=s3_listing()), patch(
        "src.istdaten_sync.config.S3_BUCKET", "b"
    ):
        plan = plan_sync(since="2026-11-12", max_days=2, today=date(2026, 11, 21))

    assert plan["operating_days"] == ["2026-11-15", "2026-11-14"]
    assert plan["stale"] is True


def test_plan_rejects_invalid_options() -> None:
    with pytest.raises(ValueError):
        plan_sync(since="21.11.2026")
    with pytest.raises(ValueError):
        plan_sync(max_days=0)


def _load(target: Any, client: MagicMock, body: bytes = CSV) -> tuple[dict, MagicMock]:
    response = MagicMock()
    response.raw = io.BytesIO(body)

    def upload(stream: Any, bucket: str, key: str, ExtraArgs: dict) -> None:
        while stream.read(7):
            pass

    client.upload_fileobj.side_effect = upload
    with patch("src.istdaten_sync.find_resource", return_value=target), patch(
        "src.istdaten_sync.open_resource_stream", return_value=response
    ), patch("src.istdaten_sync.boto3.client", return_value=client), patch(
        "src.istdaten_sync.write_run_manifest"
    ) as write_manifest, patch(
        "src.istdaten_sync.config.S3_BUCKET", "b"
    ):
        result = load_operating_day(target.operating_day)
    response.close.assert_called_once()
    return result, write_manifest


def _missing_manifest_client() -> MagicMock:
    client = MagicMock()
    client.head_object.side_effect = ClientError(
        {"Error": {"Code": "404"}}, "HeadObject"
    )
    return client


def test_load_streams_file_and_writes_manifest() -> None:
    target = resource("2026-11-20", size=len(CSV))
    client = _missing_manifest_client()
    result, write_manifest = _load(target, client)

    key = (
        "raw/istdaten_v2/dt=2026-11-20/run=istdaten-v2-2026-11-20-aaaaaaaaaaaa/data.csv"
    )
    assert result["status"] == "completed"
    assert result["uri"] == f"s3://b/{key}"
    assert client.upload_fileobj.call_args.args[1:3] == ("b", key)
    source, run_id, metadata = write_manifest.call_args.args
    assert (source, run_id) == ("istdaten_v2", "istdaten-v2-2026-11-20-aaaaaaaaaaaa")
    assert metadata["bytes"] == len(CSV)
    assert metadata["header"] == "BETRIEBSTAG;FAHRT_BEZEICHNER"
    assert metadata["ckan"]["resource_id"] == "id-2026-11-20"
    assert write_manifest.call_args.kwargs["now"].date() == date(2026, 11, 20)
    json.dumps(metadata)


def test_load_raises_on_size_mismatch_without_manifest() -> None:
    target = resource("2026-11-20", size=len(CSV) + 1)
    response = MagicMock()
    response.raw = io.BytesIO(CSV)
    client = _missing_manifest_client()
    client.upload_fileobj.side_effect = lambda s, b, k, ExtraArgs: s.read()
    with patch("src.istdaten_sync.find_resource", return_value=target), patch(
        "src.istdaten_sync.open_resource_stream", return_value=response
    ), patch("src.istdaten_sync.boto3.client", return_value=client), patch(
        "src.istdaten_sync.write_run_manifest"
    ) as write_manifest, patch(
        "src.istdaten_sync.config.S3_BUCKET", "b"
    ):
        with pytest.raises(RuntimeError, match="catalogue lists"):
            load_operating_day("2026-11-20")
    write_manifest.assert_not_called()


def test_load_skips_version_that_is_already_stored() -> None:
    client = MagicMock()
    with patch(
        "src.istdaten_sync.find_resource", return_value=resource("2026-11-20")
    ), patch("src.istdaten_sync.open_resource_stream") as open_stream, patch(
        "src.istdaten_sync.boto3.client", return_value=client
    ), patch(
        "src.istdaten_sync.config.S3_BUCKET", "b"
    ):
        result = load_operating_day("2026-11-20")

    assert result["status"] == "skipped"
    open_stream.assert_not_called()
    assert client.head_object.call_args.kwargs["Key"].endswith(
        "run=istdaten-v2-2026-11-20-aaaaaaaaaaaa/manifest.json"
    )


def test_load_latest_uses_newest_day() -> None:
    with patch(
        "src.istdaten_sync.list_istdaten_resources",
        return_value=[resource("2026-11-19"), resource("2026-11-20")],
    ), patch(
        "src.istdaten_sync.load_operating_day", return_value={"uri": "s3://b/k"}
    ) as load:
        assert load_latest() == {"uri": "s3://b/k"}
    load.assert_called_once_with("2026-11-20")


def test_metered_stream_counts_hashes_and_keeps_header() -> None:
    stream = _MeteredStream(io.BytesIO(CSV))
    assert stream.read(5) + stream.read() == CSV
    assert stream.bytes_read == len(CSV)
    assert stream.header == "BETRIEBSTAG;FAHRT_BEZEICHNER"
    assert len(stream.md5) == len(CSV_MD5)
