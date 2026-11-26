"""Tests for the Silver Ist-Daten build (Athena and S3 are mocked)."""

import json
import re
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.run import handler
from src.silver.athena import AthenaQueryFailed, run_query
from src.silver.istdaten import (
    build_day,
    newest_raw_versions,
    plan_silver_istdaten,
    render_sql,
)

BUCKET = "mscids-dwl-data-test-123"
MD5 = "0123456789abcdef0123456789abcdef"


def ts(hour: int) -> datetime:
    return datetime(2026, 11, 1, hour, tzinfo=timezone.utc)


def manifest_key(day: str, run: str) -> str:
    return f"raw/istdaten_v2/dt={day}/run={run}/manifest.json"


RAW_OBJECTS: list[dict[str, Any]] = [
    {
        "Key": manifest_key("2025-08-01", "istdaten-v2-2025-08-01-aaaa"),
        "LastModified": ts(1),
    },
    {
        "Key": "raw/istdaten_v2/dt=2025-08-01/run=istdaten-v2-2025-08-01-aaaa/data.csv",
        "LastModified": ts(1),
    },
    # replaced file: the newer manifest wins
    {
        "Key": manifest_key("2025-08-02", "istdaten-v2-2025-08-02-old"),
        "LastModified": ts(1),
    },
    {
        "Key": manifest_key("2025-08-02", "istdaten-v2-2025-08-02-new"),
        "LastModified": ts(5),
    },
    {
        "Key": manifest_key("2025-08-03", "istdaten-v2-2025-08-03-cccc"),
        "LastModified": ts(1),
    },
    # earlier permalink loader file without a run: ignored
    {"Key": "raw/istdaten_v2/dt=2025-08-04/101530.csv", "LastModified": ts(1)},
]
MARKERS: list[dict[str, Any]] = [
    {
        "Key": "silver/_state/istdaten/dt=2025-08-01/run=istdaten-v2-2025-08-01-aaaa.json"
    },
    {"Key": "silver/_state/istdaten/dt=2025-08-02/run=istdaten-v2-2025-08-02-old.json"},
]


def s3_client(markers: list[dict[str, Any]] | None = None) -> MagicMock:
    client = MagicMock()
    marker_objects = MARKERS if markers is None else markers

    def paginate(Bucket: str, Prefix: str) -> list[dict[str, Any]]:
        objects = marker_objects if Prefix.startswith("silver/") else RAW_OBJECTS
        return [{"Contents": [o for o in objects if o["Key"].startswith(Prefix)]}]

    client.get_paginator.return_value.paginate.side_effect = paginate

    def get_object(Bucket: str, Key: str) -> dict[str, Any]:
        day = Key.split("dt=")[1][:10]
        run = Key.split("run=")[1].split("/")[0]
        body = MagicMock()
        body.read.return_value = json.dumps(
            {
                "data_key": f"raw/istdaten_v2/dt={day}/run={run}/data.csv",
                "md5": MD5,
            }
        ).encode()
        return {"Body": body}

    client.get_object.side_effect = get_object
    return client


@pytest.fixture
def env() -> Any:
    with patch("src.silver.istdaten.config.S3_BUCKET", BUCKET), patch(
        "src.silver.istdaten.config.GLUE_RAW_DATABASE", "mscids_dwl_test_raw"
    ), patch(
        "src.silver.istdaten.config.GLUE_SILVER_DATABASE", "mscids_dwl_test_silver"
    ):
        yield


def test_newest_raw_version_per_day(env: Any) -> None:
    with patch("src.silver.istdaten.boto3.client", return_value=s3_client()):
        versions = newest_raw_versions()

    assert sorted(versions) == ["2025-08-01", "2025-08-02", "2025-08-03"]
    assert versions["2025-08-02"].run_id == "istdaten-v2-2025-08-02-new"


def test_plan_lists_missing_and_replaced_days(env: Any) -> None:
    with patch("src.silver.istdaten.boto3.client", return_value=s3_client()), patch(
        "src.silver.istdaten.ensure_table"
    ) as ensure:
        plan = plan_silver_istdaten()
        limited = plan_silver_istdaten(since="2025-08-03", max_days=5)
        forced = plan_silver_istdaten(until="2025-08-01", force=True)

    assert plan == {
        "items": ["2025-08-02", "2025-08-03"],
        "pending": 2,
        "up_to_date": 1,
    }
    assert limited["items"] == ["2025-08-03"]
    assert forced["items"] == ["2025-08-01"]
    assert ensure.call_count == 3


def test_plan_without_work_skips_table_creation(env: Any) -> None:
    markers = [
        {
            "Key": "silver/_state/istdaten/dt=2025-08-03/run=istdaten-v2-2025-08-03-cccc.json"
        }
    ]
    with patch(
        "src.silver.istdaten.boto3.client", return_value=s3_client(markers)
    ), patch("src.silver.istdaten.ensure_table") as ensure:
        plan = plan_silver_istdaten(since="2025-08-03")

    assert plan["items"] == []
    ensure.assert_not_called()
    with pytest.raises(ValueError):
        plan_silver_istdaten(since="2025-08-03", until="2025-08-01")


def test_render_sql_fills_placeholders_and_drops_comments() -> None:
    sql = render_sql(
        "istdaten_insert.sql",
        {
            "silver_db": "s",
            "raw_db": "r",
            "operating_day": "2025-08-01",
            "source_path": "s3://b/raw/istdaten_v2/dt=2025-08-01/run=x/data.csv",
            "source_run_id": "x",
            "source_md5": MD5,
        },
    )
    assert sql.startswith("INSERT INTO s.istdaten")
    assert "--" not in sql and "{" not in sql
    assert f"'{MD5}'" in sql
    assert "r.\"$path\" = 's3://b/raw/istdaten_v2/dt=2025-08-01/run=x/data.csv'" in sql
    assert "DATE '2025-08-01'" in sql
    with pytest.raises(ValueError, match="no value"):
        render_sql("istdaten_create.sql", {"silver_db": "s"})


def test_insert_selects_every_table_column_in_order() -> None:
    create = render_sql(
        "istdaten_create.sql", {"silver_db": "s", "silver_location": "l"}
    )
    columns = [
        line.split()[0]
        for line in create.split("(", 1)[1].split("PARTITIONED")[0].splitlines()
        if line.strip() and not line.strip().startswith(")")
    ]
    insert = render_sql(
        "istdaten_insert.sql",
        {
            "silver_db": "s",
            "raw_db": "r",
            "operating_day": "2025-08-01",
            "source_path": "p",
            "source_run_id": "x",
            "source_md5": MD5,
        },
    )
    final_select = insert.rsplit("\nSELECT", 1)[1].split("\nFROM classified")[0]
    aliases = [
        match.group(1)
        for line in final_select.splitlines()
        if (match := re.search(r"\sAS ([a-z0-9_]+),?$", line))
    ]
    assert len(columns) == 34
    assert aliases == columns


class FakeAthena:
    """Records statements and returns SUCCEEDED (or a failure for one)."""

    def __init__(self, fail_on: str | None = None, rows: str = "1234") -> None:
        self.statements: list[str] = []
        self.fail_on = fail_on
        self.rows = rows

    def start_query_execution(self, QueryString: str, WorkGroup: str) -> dict:
        self.statements.append(QueryString)
        return {"QueryExecutionId": f"q{len(self.statements)}"}

    def get_query_execution(self, QueryExecutionId: str) -> dict:
        sql = self.statements[int(QueryExecutionId[1:]) - 1]
        failed = self.fail_on is not None and sql.startswith(self.fail_on)
        return {
            "QueryExecution": {
                "Status": {
                    "State": "FAILED" if failed else "SUCCEEDED",
                    "StateChangeReason": "ICEBERG_COMMIT_ERROR",
                },
                "Statistics": {"DataScannedInBytes": 100},
            }
        }

    def get_query_results(self, QueryExecutionId: str, MaxResults: int) -> dict:
        return {
            "ResultSet": {
                "Rows": [
                    {"Data": [{"VarCharValue": "_col0"}]},
                    {"Data": [{"VarCharValue": self.rows}]},
                ]
            }
        }


def clients(s3: MagicMock, athena: FakeAthena) -> Any:
    """boto3.client is one function for both modules, so route by service."""
    return lambda service: athena if service == "athena" else s3


def test_build_day_replaces_day_and_writes_marker(env: Any) -> None:
    s3 = s3_client()
    athena = FakeAthena()
    with patch(
        "src.silver.istdaten.boto3.client", side_effect=clients(s3, athena)
    ), patch("src.silver.athena.config.ATHENA_WORKGROUP", "wg"):
        result = build_day("2025-08-02")

    delete, insert, count = athena.statements
    assert delete == (
        "DELETE FROM mscids_dwl_test_silver.istdaten "
        "WHERE operating_date = DATE '2025-08-02'"
    )
    assert (
        f"s3://{BUCKET}/raw/istdaten_v2/dt=2025-08-02/run=istdaten-v2-2025-08-02-new/data.csv"
        in insert
    )
    assert "FROM mscids_dwl_test_raw.istdaten_v2" in insert
    assert count.startswith("SELECT count(*)")
    assert result["rows"] == 1234
    assert result["source_run_id"] == "istdaten-v2-2025-08-02-new"
    assert result["data_scanned_bytes"] == 300
    # the old marker is removed before the rebuild, the new one written after it
    s3.delete_object.assert_called_once_with(
        Bucket=BUCKET,
        Key="silver/_state/istdaten/dt=2025-08-02/run=istdaten-v2-2025-08-02-old.json",
    )
    marker = s3.put_object.call_args.kwargs
    assert (
        marker["Key"]
        == "silver/_state/istdaten/dt=2025-08-02/run=istdaten-v2-2025-08-02-new.json"
    )
    assert json.loads(marker["Body"])["rows"] == 1234


def test_failed_insert_leaves_no_marker(env: Any) -> None:
    s3 = s3_client()
    athena = FakeAthena(fail_on="INSERT")
    with patch(
        "src.silver.istdaten.boto3.client", side_effect=clients(s3, athena)
    ), patch("src.silver.athena.config.ATHENA_WORKGROUP", "wg"):
        with pytest.raises(AthenaQueryFailed, match="ICEBERG_COMMIT_ERROR"):
            build_day("2025-08-01")

    s3.put_object.assert_not_called()


def test_build_rejects_empty_result_and_unknown_day(env: Any) -> None:
    s3 = s3_client()
    athena = FakeAthena(rows="0")
    with patch(
        "src.silver.istdaten.boto3.client", side_effect=clients(s3, athena)
    ), patch("src.silver.athena.config.ATHENA_WORKGROUP", "wg"):
        with pytest.raises(RuntimeError, match="no rows"):
            build_day("2025-08-03")
        with pytest.raises(LookupError):
            build_day("2025-09-01")
    s3.put_object.assert_not_called()


def test_run_query_times_out_and_stops() -> None:
    athena = MagicMock()
    athena.start_query_execution.return_value = {"QueryExecutionId": "q1"}
    athena.get_query_execution.return_value = {
        "QueryExecution": {"Status": {"State": "RUNNING"}}
    }
    with patch("src.silver.athena.boto3.client", return_value=athena), patch(
        "src.silver.athena.config.ATHENA_WORKGROUP", "wg"
    ), patch("src.silver.athena.time.sleep"):
        with pytest.raises(AthenaQueryFailed, match="timed out"):
            run_query("SELECT 1", timeout_seconds=-1)
    athena.stop_query_execution.assert_called_once_with(QueryExecutionId="q1")


def test_handler_routes_silver_actions() -> None:
    with patch("src.run.plan_silver_istdaten", return_value={"items": []}) as plan:
        handler(
            {
                "action": "plan_silver_istdaten",
                "input": {"since": "2025-08-01", "max_days": "3"},
            },
            None,
        )
    plan.assert_called_once_with(
        since="2025-08-01", until=None, max_days=3, force=False
    )

    with patch("src.run.build_silver_istdaten_day", return_value={}) as build:
        handler(
            {"action": "build_silver_istdaten", "operating_day": "2025-08-01"}, None
        )
    build.assert_called_once_with("2025-08-01")

    with pytest.raises(ValueError, match="operating_day"):
        handler({"action": "build_silver_istdaten"}, None)
