"""atlas service points (Dienststellen) from opentransportdata.swiss.

The dataset ``service-point-v2`` is the official register of all public
transport stops and operating points in Switzerland, updated daily. The "full"
export holds every version of every service point with its validity period
(``validFrom``/``validTo``), the stop identifiers used by the Ist-Daten
(``number`` = BPUIC, ``sloid``) and the BFS municipality number
(``fsoNumber``). It is a plain CSV of about 65 MB, available without a key.
"""

import hashlib
import logging
from typing import Any, BinaryIO
from urllib.parse import urlparse

from src.config import config
from src.http import get_session

logger = logging.getLogger(__name__)

USER_AGENT = "mscids-dwl-project/1.0"
ALLOWED_HOSTS = frozenset({"data.opentransportdata.swiss"})
CHUNK_SIZE = 1 << 20


def download_service_points(target: BinaryIO) -> dict[str, Any]:
    """
    Stream the full service point export into ``target``

    Args:
        target: Writable binary file (a temporary file in the Lambda)

    Returns:
        dict[str, Any]: Requested and final URL, byte count, MD5 and the
        first line of the CSV
    """
    url = config.SERVICE_POINTS_URL
    if urlparse(url).hostname not in ALLOWED_HOSTS:
        raise ValueError(f"Service point host not allowed: {url}")
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    head = b""
    with get_session().get(
        url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=(10, 300)
    ) as response:
        response.raise_for_status()
        final_url = response.url
        if urlparse(final_url).hostname not in ALLOWED_HOSTS:
            raise ValueError(f"Service point download redirected to {final_url}")
        for chunk in response.iter_content(CHUNK_SIZE):
            target.write(chunk)
            md5.update(chunk)
            size += len(chunk)
            if len(head) < 4096:
                head += chunk[: 4096 - len(head)]
    if size == 0:
        raise RuntimeError(f"{url} returned an empty file")
    header = head.split(b"\n", 1)[0].decode("utf-8-sig", errors="replace").strip()
    logger.info("Downloaded service points: %d bytes from %s", size, final_url)
    return {
        "url": url,
        "final_url": final_url,
        "bytes": size,
        "md5": md5.hexdigest(),
        "header": header,
    }
