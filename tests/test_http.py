"""Test file for http.py"""

from unittest.mock import patch

import pytest
import requests
from requests.adapters import HTTPAdapter

from src.http import get_session


def test_get_session_mounts_retry_adapter() -> None:
    """Both schemes use an adapter with the configured retry policy"""
    with patch("src.http.config.HTTP_MAX_RETRIES", 5), patch(
        "src.http.config.HTTP_BACKOFF_SECONDS", 2.0
    ):
        session = get_session()

    for prefix in ("https://", "http://"):
        adapter = session.get_adapter(prefix + "example.com")
        assert isinstance(adapter, HTTPAdapter)
        assert adapter.max_retries.total == 5
        assert adapter.max_retries.backoff_factor == 2.0
        assert 503 in (adapter.max_retries.status_forcelist or ())
        assert adapter.max_retries.allowed_methods is not None
        assert "POST" in adapter.max_retries.allowed_methods


def test_get_session_is_requests_session() -> None:
    """Returns a plain requests session"""
    assert isinstance(get_session(), requests.Session)
