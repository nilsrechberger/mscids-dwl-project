"""Shared HTTP session with retry logic"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from src.config import config


def get_session() -> requests.Session:
    """
    Build a session that retries transient failures

    Returns:
        requests.Session: Session with retry adapter mounted for http(s)
    """
    retry = Retry(
        total=config.HTTP_MAX_RETRIES,
        backoff_factor=config.HTTP_BACKOFF_SECONDS,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET", "POST"},
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
