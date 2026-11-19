"""Configuración centralizada de logs claros para AdScout."""

from __future__ import annotations

import logging
import os


def configure_logging(level: str | None = None) -> logging.Logger:
    """Configura el logger raíz de AdScout sin duplicar handlers."""
    resolved_level = (level or os.getenv("ADSCOUT_LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, resolved_level, logging.INFO)

    logger = logging.getLogger("adscout")
    logger.setLevel(numeric_level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
