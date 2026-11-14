"""Downloads the municipality file from BFS"""

import logging
from io import BytesIO

import requests
from openpyxl import load_workbook

from src.config import config
from src.http import get_session

logger = logging.getLogger(__name__)


def fetch_municipality() -> requests.Response:
    """
    Downloads the static XLSX file from the BFS

    Args:
        None

    Returns:
        requests.Response: Response containing the XLSX file
    """
    try:
        # The BFS endpoint serves the XLSX export on POST
        response = get_session().post(str(config.MUNICIPALITY_XLSX), timeout=10)

        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("%s", e)
        raise
    return response


def parse_municipality_names(xlsx: bytes) -> list[str]:
    """
    Extract the unique municipality names from the BFS XLSX file

    Args:
        xlsx: Raw content of the XLSX file

    Returns:
        list[str]: Municipality names in file order, without duplicates
    """
    sheet = load_workbook(BytesIO(xlsx), read_only=True)["Daten"]
    rows = sheet.iter_rows(values_only=True)
    column = list(next(rows)).index("Gemeindename")
    names = (row[column] for row in rows if row[column])
    return list(dict.fromkeys(str(n) for n in names))
