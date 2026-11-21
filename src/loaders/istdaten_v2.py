"""Ist-Daten v2 daily CSVs from the opentransportdata.swiss CKAN catalogue.

The CKAN ``package_show`` call lists every daily file that is currently
published (a rolling window of roughly 50 operating days). Each resource
carries the operating day in its file name and a content hash, which lets the
pipeline load missing days and detect files the provider has replaced.
The listing needs an API key; the file downloads themselves are public.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import boto3
import requests

from src.config import config
from src.http import get_session

logger = logging.getLogger(__name__)

USER_AGENT = "mscids-dwl-project/1.0"
ALLOWED_DOWNLOAD_HOSTS = frozenset({"data.opentransportdata.swiss"})
_DAY_IN_URL = re.compile(r"/(\d{4}-\d{2}-\d{2})_istdaten\.csv$", re.IGNORECASE)


@dataclass(frozen=True)
class IstdatenResource:
    """One daily Ist-Daten v2 file as listed in the CKAN catalogue."""

    operating_day: str
    resource_id: str
    url: str
    hash: str
    size: int | None
    created: str | None
    last_modified: str | None

    @property
    def fingerprint(self) -> str:
        """Short, path-safe version marker derived from the CKAN content hash."""
        cleaned = re.sub(r"[^0-9a-z]", "", self.hash.lower())
        if not cleaned:
            raise ValueError(f"Resource {self.resource_id} has no usable hash")
        return cleaned[:12]

    @property
    def run_id(self) -> str:
        """Deterministic run ID: one run per operating day and file version."""
        return f"istdaten-v2-{self.operating_day}-{self.fingerprint}"


@lru_cache(maxsize=1)
def get_ckan_api_key() -> str:
    """
    Return the CKAN API key

    Locally the key comes from ``CKAN_API_KEY``. In Lambda only the secret ID
    is configured (``CKAN_API_KEY_SECRET_ID``) and the value is read from AWS
    Secrets Manager once per container. The secret may be a plain string or
    JSON with an ``api_key`` field.
    """
    if config.CKAN_API_KEY:
        return config.CKAN_API_KEY
    if not config.CKAN_API_KEY_SECRET_ID:
        raise RuntimeError("Set CKAN_API_KEY (local) or CKAN_API_KEY_SECRET_ID")
    secret = boto3.client("secretsmanager").get_secret_value(
        SecretId=config.CKAN_API_KEY_SECRET_ID
    )["SecretString"]
    value = secret.strip()
    if value.startswith("{"):
        value = str(json.loads(value).get("api_key", "")).strip()
    if not value:
        raise RuntimeError("CKAN API key secret is empty")
    return value


def _parse_resource(raw: dict[str, Any]) -> IstdatenResource | None:
    url = str(raw.get("url") or "")
    match = _DAY_IN_URL.search(urlparse(url).path)
    if not match:
        logger.warning("Skipping CKAN resource without operating day: %s", url)
        return None
    if urlparse(url).hostname not in ALLOWED_DOWNLOAD_HOSTS:
        logger.warning("Skipping CKAN resource on unexpected host: %s", url)
        return None
    operating_day = match.group(1)
    date.fromisoformat(operating_day)
    size = raw.get("byte_size") or raw.get("size")
    return IstdatenResource(
        operating_day=operating_day,
        resource_id=str(raw.get("id") or raw.get("resource_id") or ""),
        url=url,
        hash=str(raw.get("hash") or ""),
        size=int(size) if size not in (None, "") else None,
        created=raw.get("created"),
        last_modified=raw.get("last_modified"),
    )


def list_istdaten_resources() -> list[IstdatenResource]:
    """
    List all daily files currently published in the CKAN catalogue

    Returns:
        list[IstdatenResource]: One entry per operating day, oldest first. If
        the catalogue lists a day twice, the most recently modified entry wins.
    """
    endpoint = config.ISTDATEN_V2_CKAN_ENDPOINT.rstrip("/")
    try:
        response = get_session().get(
            f"{endpoint}/package_show",
            params={"id": config.ISTDATEN_V2_DATASET_ID},
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {get_ckan_api_key()}",
                "User-Agent": USER_AGENT,
            },
            timeout=(10, 60),
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        logger.error("CKAN package_show failed: %s", error)
        raise
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError("CKAN package_show did not report success")

    by_day: dict[str, IstdatenResource] = {}
    for raw in payload["result"].get("resources", []):
        resource = _parse_resource(raw)
        if resource is None:
            continue
        current = by_day.get(resource.operating_day)
        if current is None or (resource.last_modified or "") > (
            current.last_modified or ""
        ):
            by_day[resource.operating_day] = resource
    resources = [by_day[day] for day in sorted(by_day)]
    logger.info("CKAN lists %d Ist-Daten v2 daily files", len(resources))
    return resources


def find_resource(operating_day: str) -> IstdatenResource:
    """Return the catalogue entry for one operating day or raise LookupError."""
    date.fromisoformat(operating_day)
    for resource in list_istdaten_resources():
        if resource.operating_day == operating_day:
            return resource
    raise LookupError(f"No Ist-Daten v2 file for {operating_day} in the catalogue")


def open_resource_stream(resource: IstdatenResource) -> requests.Response:
    """
    Open a streaming download for one daily file

    The download is public, so the API key is deliberately not sent.
    """
    try:
        response = get_session().get(
            resource.url,
            headers={"Accept": "text/csv", "User-Agent": USER_AGENT},
            stream=True,
            timeout=(10, 600),
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        logger.error("Ist-Daten v2 download failed for %s: %s", resource.url, error)
        raise
    response.raw.decode_content = True
    logger.info(
        "Streaming Ist-Daten v2 %s from %s", resource.operating_day, resource.url
    )
    return response
