"""Tests for the atlas service point load (network and S3 are mocked)."""

import hashlib
import io
import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.loaders.service_points import download_service_points
from src.run import handler
from src.service_points_sync import (
    SILVER_COLUMNS,
    build_silver_rows,
    load_service_points,
    parse_date,
)

HEADER = (
    "sloid;number;designationOfficial;validFrom;validTo;status;stopPoint;"
    "meansOfTransport;fsoNumber;municipalityName;cantonAbbreviation;"
    "localityName;wgs84East;wgs84North"
)
CSV = (
    "﻿"
    + HEADER
    + "\n"
    + "ch:1:sloid:3000;8503000;Zürich HB;01.01.2020;31.12.2025;VALIDATED;true;"
    "TRAIN;261;Zürich;ZH;Zürich;8.540192;47.378177\n"
    + "ch:1:sloid:3000;8503000;Zürich HB;01.01.2026;31.12.2099;VALIDATED;true;"
    "TRAIN;261;Zürich;ZH;Zürich;8.540192;47.378177\n"
    + 'ch:1:sloid:9999;8509999;"Old;Stop";01.01.2020;31.12.2099;REVOKED;true;'
    "BUS;1;A;ZH;A;8.5;47.3\n"
    + "ch:1:sloid:1234;8501234;Operating point;2024-01-01;2099-12-31;VALIDATED;"
    "false;;;;;;;\n"
)


def test_parse_date_accepts_both_formats() -> None:
    assert parse_date("29.07.2022") == "2022-07-29"
    assert parse_date("2022-07-29") == "2022-07-29"
    assert parse_date("") == ""


def test_silver_rows_drop_revoked_and_flag_latest_version() -> None:
    rows, counters = build_silver_rows(io.StringIO(CSV.lstrip("﻿")), "run-1")

    assert counters == {
        "input_rows": 4,
        "dropped_status": 1,
        "without_municipality": 1,
        "silver_rows": 3,
        "stop_numbers": 2,
        "stop_points": 2,
    }
    zurich = [row for row in rows if row["number"] == "8503000"]
    assert [row["valid_from"] for row in zurich] == ["2020-01-01", "2026-01-01"]
    assert [row["is_latest_version"] for row in zurich] == ["false", "true"]
    assert zurich[1]["municipality_gdenr"] == "261"
    assert zurich[1]["wgs84_east"] == "8.540192"
    assert set(rows[0]) == set(SILVER_COLUMNS)
    assert rows[2]["municipality_gdenr"] == "" and rows[2]["is_stop_point"] == "false"


def test_missing_required_column_fails() -> None:
    with pytest.raises(ValueError, match="fsoNumber"):
        build_silver_rows(io.StringIO("sloid;number\nx;1\n"), "run-1")


class FakeResponse:
    def __init__(self, body: bytes, url: str) -> None:
        self.body = body
        self.url = url

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, size: int) -> Any:
        return iter([self.body[i : i + 7] for i in range(0, len(self.body), 7)])


def session_for(body: bytes, url: str) -> MagicMock:
    session = MagicMock()
    session.get.return_value = FakeResponse(body, url)
    return session


def test_download_streams_and_hashes() -> None:
    body = CSV.encode("utf-8")
    target = io.BytesIO()
    url = "https://data.opentransportdata.swiss/dataset/x/download/full.csv"
    with patch(
        "src.loaders.service_points.get_session", return_value=session_for(body, url)
    ):
        result = download_service_points(target)

    assert target.getvalue() == body
    assert result["md5"] == hashlib.md5(body).hexdigest()
    assert result["header"] == HEADER
    with patch(
        "src.loaders.service_points.get_session",
        return_value=session_for(body, "https://evil.example/x.csv"),
    ):
        with pytest.raises(ValueError, match="redirected"):
            download_service_points(io.BytesIO())


def s3_client(previous_md5: str | None) -> MagicMock:
    client = MagicMock()
    contents = (
        []
        if previous_md5 is None
        else [
            {
                "Key": "raw/service_points/dt=2026-11-20/run=r/manifest.json",
                "LastModified": datetime(2026, 11, 20, tzinfo=timezone.utc),
            }
        ]
    )
    client.get_paginator.return_value.paginate.return_value = [{"Contents": contents}]
    body = MagicMock()
    body.read.return_value = json.dumps(
        {"md5": previous_md5, "run_id": "service-points-old"}
    ).encode()
    client.get_object.return_value = {"Body": body}
    uploaded: dict[str, bytes] = {}

    def upload(stream: Any, bucket: str, key: str, ExtraArgs: dict) -> None:
        uploaded[key] = stream.read()

    client.upload_fileobj.side_effect = upload
    client.uploaded = uploaded
    return client


def run_load(client: MagicMock, force: bool = False) -> tuple[dict, MagicMock]:
    body = CSV.encode("utf-8")
    url = "https://data.opentransportdata.swiss/x/full.csv"
    with patch(
        "src.loaders.service_points.get_session", return_value=session_for(body, url)
    ), patch("src.service_points_sync.boto3.client", return_value=client), patch(
        "src.service_points_sync.config.S3_BUCKET", "b"
    ), patch(
        "src.service_points_sync.write_run_manifest"
    ) as manifest:
        return load_service_points(force=force), manifest


def test_load_stores_raw_and_silver_when_changed() -> None:
    client = s3_client(previous_md5="0" * 32)
    result, manifest = run_load(client)

    assert result["status"] == "loaded"
    md5 = hashlib.md5(CSV.encode("utf-8")).hexdigest()
    assert result["run_id"].endswith(md5[:12])
    ((raw_key, raw_body),) = client.uploaded.items()
    assert raw_key.startswith("raw/service_points/dt=")
    assert raw_key.endswith(f"/run={result['run_id']}/data.csv")
    assert raw_body == CSV.encode("utf-8")
    silver = client.put_object.call_args.kwargs
    assert silver["Key"] == "silver/service_points/service_points.tsv"
    lines = silver["Body"].decode().splitlines()
    assert lines[0].split("\t") == SILVER_COLUMNS
    assert len(lines) == 4
    metadata = manifest.call_args.args[2]
    assert metadata["md5"] == md5 and metadata["silver_rows"] == 3


def test_load_skips_unchanged_content_unless_forced() -> None:
    md5 = hashlib.md5(CSV.encode("utf-8")).hexdigest()
    client = s3_client(previous_md5=md5)
    result, manifest = run_load(client)

    assert result == {"status": "unchanged", "md5": md5, "run_id": "service-points-old"}
    client.upload_fileobj.assert_not_called()
    client.put_object.assert_not_called()
    manifest.assert_not_called()

    forced, _ = run_load(s3_client(previous_md5=md5), force=True)
    assert forced["status"] == "loaded"


def test_handler_routes_service_points() -> None:
    with patch("src.run.load_service_points", return_value={"status": "x"}) as load:
        assert handler({"source": "service_points", "force": True}, None) == {
            "status": "x"
        }
    load.assert_called_once_with(force=True)
