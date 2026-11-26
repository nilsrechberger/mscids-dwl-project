"""Run Athena statements from the Lambda and wait for them to finish."""

import logging
import time
from typing import Any

import boto3

from src.config import config

logger = logging.getLogger(__name__)

TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}


class AthenaQueryFailed(RuntimeError):
    """An Athena statement ended in FAILED or CANCELLED."""


def run_query(
    sql: str, poll_seconds: float = 2.0, timeout_seconds: float = 780.0
) -> dict[str, Any]:
    """
    Execute one statement in the configured workgroup and wait for it

    Args:
        sql: The statement (fully qualified table names, no trailing ';')
        poll_seconds: Pause between status checks
        timeout_seconds: Give up (and stop the query) after this long, below
            the Lambda timeout

    Returns:
        dict[str, Any]: Query execution ID, scanned bytes and engine time

    Raises:
        AthenaQueryFailed: The statement failed, was cancelled or timed out
    """
    if not config.ATHENA_WORKGROUP:
        raise RuntimeError("ATHENA_WORKGROUP is not set")
    client = boto3.client("athena")
    query_id = client.start_query_execution(
        QueryString=sql, WorkGroup=config.ATHENA_WORKGROUP
    )["QueryExecutionId"]
    deadline = time.monotonic() + timeout_seconds
    while True:
        execution = client.get_query_execution(QueryExecutionId=query_id)[
            "QueryExecution"
        ]
        status = execution["Status"]
        state = status["State"]
        if state in TERMINAL_STATES:
            break
        if time.monotonic() > deadline:
            client.stop_query_execution(QueryExecutionId=query_id)
            raise AthenaQueryFailed(f"Athena query {query_id} timed out")
        time.sleep(poll_seconds)
    if state != "SUCCEEDED":
        reason = status.get("StateChangeReason", "no reason given")
        raise AthenaQueryFailed(f"Athena query {query_id} {state}: {reason}")
    statistics = execution.get("Statistics", {})
    result = {
        "query_execution_id": query_id,
        "data_scanned_bytes": int(statistics.get("DataScannedInBytes", 0)),
        "engine_ms": int(statistics.get("EngineExecutionTimeInMillis", 0)),
    }
    logger.info("Athena query %s succeeded: %s", query_id, result)
    return result


def first_value(query_execution_id: str) -> str | None:
    """First column of the first data row of a finished SELECT."""
    rows = boto3.client("athena").get_query_results(
        QueryExecutionId=query_execution_id, MaxResults=2
    )["ResultSet"]["Rows"]
    if len(rows) < 2:
        return None
    data = rows[1].get("Data", [])
    return data[0].get("VarCharValue") if data else None
