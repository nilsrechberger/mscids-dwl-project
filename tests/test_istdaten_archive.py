"""Tests for the Ist-Daten v2 monthly archive import (range-read ZIPs)."""

import hashlib
import io
import re
import zipfile
import zlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.istdaten_sync import load_archive_day, plan_archive_import
from src.loaders.istdaten_archive import (
    ArchiveMember,
    ArchiveNotFound,
    HttpRangeFile,
    archive_url,
    list_archive_members,
)
from src.run import handler

DAY_1 = b"\xef\xbb\xbfBETRIEBSTAG;FAHRT_BEZEICHNER\n01.08.2025;1\n" * 200
DAY_2 = b"\xef\xbb\xbfBETRIEBSTAG;FAHRT_BEZEICHNER\n02.08.2025;2\n" * 200
URL = "https://archive.opentransportdata.swiss/istdaten/2025/ist-daten-v2-2025-08.zip"


def build_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("2025-08-02_IstDaten.csv", DAY_2)
        archive.writestr("2025-08-01_IstDaten.csv", DAY_1)
        archive.writestr("readme.txt", b"not a daily file")
    return buffer.getvalue()


class FakeRaw:
    def __init__(self, data: bytes) -> None:
        self._data = io.BytesIO(data)

    def read(self, amount: int = -1, decode_content: Any = None) -> bytes:
        return self._data.read(amount)


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"", content_range: str = ""):
        self.status_code = status
        self.headers = {"Content-Range": content_range} if content_range else {}
        self.raw = FakeRaw(body)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self) -> None:
        pass


class FakeServer:
    """Serves byte ranges of one in-memory file, like the archive host."""

    def __init__(self, data: bytes, status: int = 206) -> None:
        self.data = data
        self.status = status
        self.ranges: list[str] = []

    def get(self, url: str, headers: dict[str, str], **_: Any) -> FakeResponse:
        range_header = headers["Range"]
        self.ranges.append(range_header)
        if self.status != 206:
            return FakeResponse(self.status, self.data)
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
        assert match, range_header
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else len(self.data) - 1
        return FakeResponse(
            206,
            self.data[start : end + 1],
            f"bytes {start}-{end}/{len(self.data)}",
        )


def test_archive_url_validates_month() -> None:
    assert archive_url("2025-08") == URL
    with pytest.raises(ValueError):
        archive_url("2025-13")


def test_lists_daily_members_with_crc_fingerprint() -> None:
    server = FakeServer(build_zip())
    with patch("src.loaders.istdaten_archive.get_session", return_value=server):
        members = list_archive_members("2025-08")

    assert [m.operating_day for m in members] == ["2025-08-01", "2025-08-02"]
    first = members[0]
    assert first.file_size == len(DAY_1)
    assert first.fingerprint == f"{zlib.crc32(DAY_1):08x}"
    assert first.run_id == f"istdaten-v2-2025-08-01-{first.fingerprint}"
    assert first.url == URL
    # size probe plus a few reads near the end of the file, never the whole ZIP
    assert len(server.ranges) <= 4


def test_sequential_reads_reuse_one_request() -> None:
    server = FakeServer(bytes(range(256)) * 100)
    remote = HttpRangeFile(URL, session=server)  # type: ignore[arg-type]
    remote.seek(1000)
    assert remote.read(10) == (bytes(range(256)) * 100)[1000:1010]
    remote.read(500)
    remote.seek(0)
    remote.read(5)
    assert server.ranges == ["bytes=0-0", "bytes=1000-", "bytes=0-"]


def test_missing_archive_and_ignored_range_raise() -> None:
    with pytest.raises(ArchiveNotFound):
        HttpRangeFile(URL, session=FakeServer(b"", status=404))  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="ignored the range request"):
        HttpRangeFile(URL, session=FakeServer(b"zip", status=200))  # type: ignore[arg-type]


def member(day: str, month: str = "2025-08") -> ArchiveMember:
    return ArchiveMember(day, month, URL, f"{day}_IstDaten.csv", 1, 10, 100)


def test_plan_skips_loaded_days_and_reports_missing_months() -> None:
    def members_for(month: str) -> list[ArchiveMember]:
        if month == "2025-09":
            raise ArchiveNotFound(month)
        return (
            [member("2025-07-31", "2025-07")]
            if month == "2025-07"
            else [
                member("2025-08-01"),
                member("2025-08-02"),
                member("2025-08-03"),
            ]
        )

    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {
            "Contents": [
                {
                    "Key": "raw/istdaten_v2/dt=2025-08-02/"
                    "run=istdaten-v2-2025-08-02-0000abcd/manifest.json"
                }
            ]
        }
    ]
    with patch(
        "src.istdaten_sync.list_archive_members", side_effect=members_for
    ), patch("src.istdaten_sync.boto3.client", return_value=client), patch(
        "src.istdaten_sync.config.S3_BUCKET", "b"
    ):
        plan = plan_archive_import("2025-08-01", "2025-09-30")
        limited = plan_archive_import("2025-08-01", "2025-09-30", max_days=1)

    assert plan["items"] == [
        {"operating_day": "2025-08-01", "archive_month": "2025-08"},
        {"operating_day": "2025-08-03", "archive_month": "2025-08"},
    ]
    assert plan["available"] == 3
    assert plan["already_loaded"] == 1
    assert plan["missing_months"] == ["2025-09"]
    assert limited["items"] == plan["items"][:1]
    with pytest.raises(ValueError):
        plan_archive_import("2025-09-01", "2025-08-01")


def s3_client(existing_keys: list[str] | None = None) -> tuple[MagicMock, dict]:
    client = MagicMock()
    client.list_objects_v2.return_value = {
        "Contents": [{"Key": key} for key in existing_keys or []]
    }
    uploaded: dict[str, Any] = {}

    def upload(stream: Any, bucket: str, key: str, ExtraArgs: dict) -> None:
        uploaded["key"] = key
        uploaded["body"] = b"".join(iter(lambda: stream.read(1024), b""))

    client.upload_fileobj.side_effect = upload
    return client, uploaded


def test_load_archive_day_streams_member_and_writes_manifest() -> None:
    server = FakeServer(build_zip())
    client, uploaded = s3_client()
    with patch("src.loaders.istdaten_archive.get_session", return_value=server), patch(
        "src.istdaten_sync.boto3.client", return_value=client
    ), patch("src.istdaten_sync.write_run_manifest") as manifest, patch(
        "src.istdaten_sync.config.S3_BUCKET", "b"
    ):
        result = load_archive_day("2025-08-01")

    fingerprint = f"{zlib.crc32(DAY_1):08x}"
    run_id = f"istdaten-v2-2025-08-01-{fingerprint}"
    assert uploaded["body"] == DAY_1
    assert uploaded["key"] == f"raw/istdaten_v2/dt=2025-08-01/run={run_id}/data.csv"
    assert result["status"] == "completed"
    assert result["run_id"] == run_id
    source, manifest_run_id, metadata = manifest.call_args.args
    assert (source, manifest_run_id) == ("istdaten_v2", run_id)
    assert metadata["origin"] == "archive"
    assert metadata["bytes"] == len(DAY_1)
    assert metadata["md5"] == hashlib.md5(DAY_1).hexdigest()
    assert metadata["header"] == "BETRIEBSTAG;FAHRT_BEZEICHNER"
    assert metadata["archive"]["crc32"] == fingerprint
    assert metadata["archive"]["member"] == "2025-08-01_IstDaten.csv"


def test_load_archive_day_skips_days_with_any_loaded_version() -> None:
    client, _ = s3_client(
        [
            "raw/istdaten_v2/dt=2025-08-01/run=istdaten-v2-2025-08-01-"
            "abcdef123456/manifest.json"
        ]
    )
    with patch("src.loaders.istdaten_archive.get_session") as session, patch(
        "src.istdaten_sync.boto3.client", return_value=client
    ), patch("src.istdaten_sync.config.S3_BUCKET", "b"):
        result = load_archive_day("2025-08-01")

    assert result["status"] == "skipped"
    assert result["existing_versions"] == ["abcdef123456"]
    session.assert_not_called()
    client.upload_fileobj.assert_not_called()


def test_corrupt_member_fails_without_manifest() -> None:
    data = bytearray(build_zip())
    entry = data.index(b"PK\x01\x02")
    # Flip the CRC32 of the first central-directory entry (2025-08-02).
    data[entry + 16] ^= 0xFF
    server = FakeServer(bytes(data))
    client, _ = s3_client()
    with patch("src.loaders.istdaten_archive.get_session", return_value=server), patch(
        "src.istdaten_sync.boto3.client", return_value=client
    ), patch("src.istdaten_sync.write_run_manifest") as manifest, patch(
        "src.istdaten_sync.config.S3_BUCKET", "b"
    ):
        with pytest.raises(zipfile.BadZipFile, match="CRC"):
            load_archive_day("2025-08-02")
    manifest.assert_not_called()


def test_handler_routes_archive_plan_and_load() -> None:
    with patch("src.run.plan_archive_import", return_value={"items": []}) as plan:
        handler(
            {
                "action": "plan_istdaten_archive",
                "input": {"since": "2025-08-01", "until": "2025-08-31", "max_days": 2},
            },
            None,
        )
    plan.assert_called_once_with("2025-08-01", "2025-08-31", 2)

    with patch("src.run.load_archive_day", return_value={}) as load:
        handler(
            {
                "source": "istdaten_v2",
                "operating_day": "2025-08-01",
                "archive_month": "2025-08",
            },
            None,
        )
    load.assert_called_once_with("2025-08-01", "2025-08")

    with pytest.raises(ValueError, match="since"):
        handler({"action": "plan_istdaten_archive", "input": {}}, None)
