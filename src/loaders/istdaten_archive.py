"""Ist-Daten v2 monthly ZIP archives from archive.opentransportdata.swiss.

Days that have dropped out of the CKAN window are published as one ZIP per
month (``istdaten/<YYYY>/ist-daten-v2-<YYYY-MM>.zip``) with one CSV per
operating day (``<YYYY-MM-DD>_IstDaten.csv``). A month is about 1.2-1.5 GB
compressed, so the archive is never downloaded as a whole: the server answers
HTTP range requests, and :class:`HttpRangeFile` exposes the remote ZIP as a
seekable file. ``zipfile`` then reads only the central directory and the one
member that is needed, decompresses it while streaming and verifies its CRC32.
"""

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

import requests

from src.config import config
from src.http import get_session

logger = logging.getLogger(__name__)

USER_AGENT = "mscids-dwl-project/1.0"
ALLOWED_ARCHIVE_HOSTS = frozenset({"archive.opentransportdata.swiss"})
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DAY_IN_MEMBER = re.compile(r"(?:^|/)(\d{4}-\d{2}-\d{2})_istdaten\.csv$", re.IGNORECASE)
_CONTENT_RANGE_TOTAL = re.compile(r"/(\d+)$")


class ArchiveNotFound(LookupError):
    """The monthly archive does not exist (yet)."""


@dataclass(frozen=True)
class ArchiveMember:
    """One daily CSV inside a monthly archive."""

    operating_day: str
    month: str
    url: str
    name: str
    crc32: int
    compressed_size: int
    file_size: int

    @property
    def fingerprint(self) -> str:
        """Path-safe version marker: the member's CRC32 as 8 hex digits."""
        return f"{self.crc32:08x}"

    @property
    def run_id(self) -> str:
        """Deterministic run ID, same pattern as the CKAN sync."""
        return f"istdaten-v2-{self.operating_day}-{self.fingerprint}"


def validate_month(month: str) -> str:
    """Return ``month`` if it is YYYY-MM, else raise ValueError."""
    if not _MONTH.match(month):
        raise ValueError(f"month must be YYYY-MM, got {month!r}")
    return month


def archive_url(month: str) -> str:
    """URL of the monthly Ist-Daten v2 archive."""
    validate_month(month)
    base = config.ISTDATEN_ARCHIVE_BASE_URL.rstrip("/")
    url = f"{base}/{month[:4]}/ist-daten-v2-{month}.zip"
    if urlparse(url).hostname not in ALLOWED_ARCHIVE_HOSTS:
        raise ValueError(f"Archive host not allowed: {url}")
    return url


class HttpRangeFile(io.RawIOBase):
    """
    Read-only, seekable view of a remote file via HTTP range requests

    Sequential reads reuse one open streaming response, so reading a ZIP member
    from start to end costs a single request; every jump (``seek`` to another
    position followed by ``read``) opens a new ``Range: bytes=<pos>-`` request.
    """

    def __init__(self, url: str, session: requests.Session | None = None) -> None:
        super().__init__()
        self.url = url
        self._session = session or get_session()
        self._pos = 0
        self._response: requests.Response | None = None
        self._response_pos = -1
        self.requests = 0
        self.size = self._probe_size()

    def _get(self, range_header: str, stream: bool) -> requests.Response:
        self.requests += 1
        response = self._session.get(
            self.url,
            headers={
                "Range": range_header,
                "Accept-Encoding": "identity",
                "User-Agent": USER_AGENT,
            },
            stream=stream,
            timeout=(10, 300),
        )
        if response.status_code == 404:
            response.close()
            raise ArchiveNotFound(self.url)
        response.raise_for_status()
        if response.status_code != 206:
            response.close()
            raise RuntimeError(
                f"{self.url} ignored the range request (HTTP {response.status_code})"
            )
        return response

    def _probe_size(self) -> int:
        response = self._get("bytes=0-0", stream=False)
        match = _CONTENT_RANGE_TOTAL.search(response.headers.get("Content-Range", ""))
        response.close()
        if not match:
            raise RuntimeError(f"{self.url} returned no usable Content-Range header")
        return int(match.group(1))

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            position = offset
        elif whence == io.SEEK_CUR:
            position = self._pos + offset
        elif whence == io.SEEK_END:
            position = self.size + offset
        else:
            raise ValueError(f"invalid whence {whence}")
        if position < 0:
            raise ValueError("negative seek position")
        self._pos = position
        return position

    def _close_response(self) -> None:
        if self._response is not None:
            self._response.close()
        self._response = None
        self._response_pos = -1

    def readinto(self, buffer: Any) -> int:
        view = memoryview(buffer).cast("B")
        if not len(view) or self._pos >= self.size:
            return 0
        if self._response is None or self._response_pos != self._pos:
            self._close_response()
            self._response = self._get(f"bytes={self._pos}-", stream=True)
            self._response_pos = self._pos
        chunk = self._response.raw.read(
            min(len(view), self.size - self._pos), decode_content=False
        )
        if not chunk:
            raise EOFError(f"{self.url}: connection ended at byte {self._pos}")
        view[: len(chunk)] = chunk
        self._pos += len(chunk)
        self._response_pos = self._pos
        return len(chunk)

    def close(self) -> None:
        self._close_response()
        super().close()


def _member_for(info: zipfile.ZipInfo, month: str, url: str) -> ArchiveMember | None:
    match = _DAY_IN_MEMBER.search(info.filename)
    if not match or info.is_dir():
        return None
    operating_day = match.group(1)
    date.fromisoformat(operating_day)
    return ArchiveMember(
        operating_day=operating_day,
        month=month,
        url=url,
        name=info.filename,
        crc32=info.CRC,
        compressed_size=info.compress_size,
        file_size=info.file_size,
    )


def open_archive(month: str) -> tuple[zipfile.ZipFile, list[ArchiveMember]]:
    """
    Open one monthly archive and list its daily CSVs

    Only the ZIP central directory is downloaded. The caller must close the
    returned ``ZipFile``.

    Args:
        month: Archive month (YYYY-MM)

    Returns:
        tuple[zipfile.ZipFile, list[ArchiveMember]]: The open archive and its
        daily members, oldest first

    Raises:
        ArchiveNotFound: The archive for this month is not published (yet)
    """
    url = archive_url(month)
    remote = HttpRangeFile(url)
    try:
        archive = zipfile.ZipFile(io.BufferedReader(remote, buffer_size=1 << 20))
    except Exception:
        remote.close()
        raise
    members: dict[str, ArchiveMember] = {}
    for info in archive.infolist():
        member = _member_for(info, month, url)
        if member is None:
            logger.warning(
                "Skipping unexpected archive entry %s in %s", info.filename, url
            )
            continue
        if member.operating_day in members:
            raise RuntimeError(f"{url} contains {member.operating_day} twice")
        members[member.operating_day] = member
    ordered = [members[day] for day in sorted(members)]
    logger.info(
        "Archive %s: %d daily files (%d bytes, %d range requests)",
        month,
        len(ordered),
        remote.size,
        remote.requests,
    )
    return archive, ordered


def list_archive_members(month: str) -> list[ArchiveMember]:
    """List the daily CSVs of one monthly archive (central directory only)."""
    archive, members = open_archive(month)
    archive.close()
    return members
