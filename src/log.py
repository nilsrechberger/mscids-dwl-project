"""Project logging configuration"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d %(levelname)-8s "
    "%(name)s:%(funcName)s:%(lineno)d [%(threadName)s] %(message)s"
)


def setup_logging(level: int = logging.DEBUG, to_file: bool = True) -> None:
    """Configure root logging once. Call from the application entry point."""

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if to_file:
        LOG_DIR.mkdir(exist_ok=True)
        handlers.append(
            RotatingFileHandler(LOG_DIR / "dwl.log", maxBytes=10_000_000, backupCount=5)
        )
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
