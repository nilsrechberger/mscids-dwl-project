"""Shared pytest fixtures"""

from pathlib import Path

import pytest


@pytest.fixture
def output_dir() -> Path:
    """Directory for local inspection dumps (gitignored)"""

    path = Path(__file__).parent / "output"
    path.mkdir(exist_ok=True)
    return path
