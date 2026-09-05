"""
Structured Logging Configuration
"""

import logging
import sys
from app.config import settings


def setup_logging() -> logging.Logger:
    """Configures structured logger for ClosureIQ."""
    logger = logging.getLogger("closureiq")
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(log_level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
