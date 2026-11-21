"""Tests for the Ist-Daten v2 CKAN loader."""

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.loaders import istdaten_v2
from src.loaders.istdaten_v2 import (
    IstdatenResource,
    find_resource,
    get_ckan_api_key,
    list_istdaten_resources,
    open_resource_stream,
)

BASE = "https://data.opentransportdata.swiss/dataset/d/resource"


def ckan_resource(
    day: str, hash_: str = "5b3a252466813a4160bfed26c8ef645d", **extra: Any
) -> dict[str, Any]:
    return {
        "id": f"id-{day}",
        "url": f"{BASE}/id-{day}/download/{day}_istdaten.csv",
        "hash": hash_,
        "byte_size": 100,
        "created": f"{day}T04:12:00+01:00",
        "last_modified": f"{day}T04:12:00+01:00",
        **extra,
    }


@pytest.fixture(autouse=True)
def api_key() -> Iterator[None]:
    get_ckan_api_key.cache_clear()
    with patch.object(istdaten_v2.config, "CKAN_API_KEY", "test-key"):
        yield
    get_ckan_api_key.cache_clear()


def _session_returning(payload: dict[str, Any]) -> MagicMock:
    session = MagicMock()
    session.get.return_value.json.return_value = payload
    return session


def test_list_resources_sorts_and_authenticates() -> None:
    payload = {
        "success": True,
        "result": {
            "resources": [
                ckan_resource("2026-11-20"),
                ckan_resource("2026-11-19"),
                {"id": "x", "url": f"{BASE}/x/download/readme.pdf"},
            ]
        },
    }
    session = _session_returning(payload)
    with patch("src.loaders.istdaten_v2.get_session", return_value=session):
        resources = list_istdaten_resources()

    assert [r.operating_day for r in resources] == ["2026-11-19", "2026-11-20"]
    assert resources[1].size == 100
    kwargs = session.get.call_args.kwargs
    assert session.get.call_args.args[0].endswith("/ckan-api/package_show")
    assert kwargs["params"] == {"id": "ist-daten-v2"}
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"


def test_list_resources_keeps_newest_duplicate_and_skips_foreign_hosts() -> None:
    older = ckan_resource("2026-11-19", hash_="a" * 32)
    newer = ckan_resource("2026-11-19", hash_="b" * 32)
    newer["last_modified"] = "2026-11-25T10:00:00+01:00"
    foreign = ckan_resource("2026-11-18")
    foreign["url"] = "https://evil.example/download/2026-11-18_istdaten.csv"
    session = _session_returning(
        {"success": True, "result": {"resources": [newer, older, foreign]}}
    )
    with patch("src.loaders.istdaten_v2.get_session", return_value=session):
        resources = list_istdaten_resources()

    assert len(resources) == 1
    assert resources[0].hash == "b" * 32


def test_list_resources_rejects_unsuccessful_response() -> None:
    session = _session_returning({"success": False})
    with patch("src.loaders.istdaten_v2.get_session", return_value=session):
        with pytest.raises(RuntimeError):
            list_istdaten_resources()


def test_list_resources_re_raises_request_error() -> None:
    session = MagicMock()
    session.get.side_effect = requests.exceptions.Timeout("slow")
    with patch("src.loaders.istdaten_v2.get_session", return_value=session):
        with pytest.raises(requests.exceptions.Timeout):
            list_istdaten_resources()


def test_find_resource_raises_for_unknown_day() -> None:
    session = _session_returning(
        {"success": True, "result": {"resources": [ckan_resource("2026-11-20")]}}
    )
    with patch("src.loaders.istdaten_v2.get_session", return_value=session):
        assert find_resource("2026-11-20").operating_day == "2026-11-20"
        with pytest.raises(LookupError):
            find_resource("2026-11-01")


def test_resource_run_id_uses_hash_prefix() -> None:
    resource = IstdatenResource(
        "2026-11-20", "id", "url", "5B3A252466813A41", None, None, None
    )
    assert resource.run_id == "istdaten-v2-2026-11-20-5b3a25246681"
    with pytest.raises(ValueError):
        _ = IstdatenResource("2026-11-20", "id", "url", "", None, None, None).run_id


def test_open_resource_stream_does_not_send_api_key() -> None:
    resource = IstdatenResource(
        "2026-11-20", "id", f"{BASE}/id/download/x.csv", "abc", 1, None, None
    )
    response = MagicMock()
    with patch("src.loaders.istdaten_v2.get_session") as get_session:
        get_session.return_value.get.return_value = response
        assert open_resource_stream(resource) is response

    kwargs = get_session.return_value.get.call_args.kwargs
    assert "Authorization" not in kwargs["headers"]
    assert kwargs["stream"] is True
    assert response.raw.decode_content is True


def test_api_key_from_secrets_manager_json() -> None:
    get_ckan_api_key.cache_clear()
    client = MagicMock()
    client.get_secret_value.return_value = {
        "SecretString": json.dumps({"api_key": "from-secret"})
    }
    with patch.object(istdaten_v2.config, "CKAN_API_KEY", None), patch.object(
        istdaten_v2.config, "CKAN_API_KEY_SECRET_ID", "arn:secret"
    ), patch("src.loaders.istdaten_v2.boto3.client", return_value=client):
        assert get_ckan_api_key() == "from-secret"
        assert get_ckan_api_key() == "from-secret"

    client.get_secret_value.assert_called_once_with(SecretId="arn:secret")


def test_api_key_requires_configuration() -> None:
    get_ckan_api_key.cache_clear()
    with patch.object(istdaten_v2.config, "CKAN_API_KEY", None), patch.object(
        istdaten_v2.config, "CKAN_API_KEY_SECRET_ID", None
    ):
        with pytest.raises(RuntimeError):
            get_ckan_api_key()
