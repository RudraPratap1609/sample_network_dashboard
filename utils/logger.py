"""
utils/logger.py
===============
Centralised logging for the HFCL EMS project.

Usage
-----
    from utils.logger import get_logger
    log = get_logger(__name__)
    log.info("Processing KPI data…")
"""

import logging
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s  —  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Return a named logger that writes to stdout with a consistent format.

    Parameters
    ----------
    name  : module name (pass __name__ from the calling module).
    level : logging level (default INFO).
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger