"""Download the official Ist-Daten v2 daily CSV as an unchanged stream."""

import logging

import requests

from src.config import config
from src.http import get_session

logger = logging.getLogger(__name__)


def fetch_istdaten_v2() -> requests.Response:
    """Return a streaming response for the configured Ist-Daten v2 file."""
    if not config.ISTDATEN_V2_ENDPOINT:
        raise RuntimeError("ISTDATEN_V2_ENDPOINT is not set")
    try:
        response = get_session().get(
            config.ISTDATEN_V2_ENDPOINT,
            headers={"Accept": "text/csv", "User-Agent": "mscids-dwl-project/1.0"},
            stream=True,
            timeout=(10, 600),
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        logger.error("Ist-Daten v2 request failed: %s", error)
        raise
    response.raw.decode_content = True
    logger.info("Fetched Ist-Daten v2 stream from %s", config.ISTDATEN_V2_ENDPOINT)
    return response
