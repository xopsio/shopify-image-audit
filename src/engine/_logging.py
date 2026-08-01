"""
Centralised logging for the audit pipeline (Sprint 6, TD-4).

A single ``logging.Logger`` named ``"shopify_image_audit"`` is exposed via
``get_logger()``. Levels are tuned so the default ``WARNING`` keeps CLI
output clean while ``LOG_LEVEL=DEBUG`` gives operators full visibility.

Configuration is idempotent: calling ``configure()`` multiple times (e.g.
from a CLI ``main()`` entry-point and again from a test fixture) resets
the handlers and reapplies the level. This makes it safe to call from
anywhere without leaking handlers.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TextIO

_LOGGER_NAME = "shopify_image_audit"
_DEFAULT_LEVEL = logging.WARNING

_configured = False


def get_logger() -> logging.Logger:
    """Return the module-level logger for the audit pipeline."""
    return logging.getLogger(_LOGGER_NAME)


def configure(
    level: int | None = None,
    *,
    stream: TextIO | None = None,
) -> None:
    """Configure the audit-pipeline logger.

    Args:
        level: Logging level (e.g. ``logging.INFO``). If ``None``, the
            ``LOG_LEVEL`` env var is consulted (defaulting to WARNING).
        stream: Stream for the handler. If ``None``, ``sys.stderr`` is used.

    Safe to call multiple times — each call resets the handlers.
    """
    global _configured
    logger = get_logger()

    if level is None:
        level_name = os.environ.get("LOG_LEVEL", "").strip().upper()
        level = getattr(logging, level_name, _DEFAULT_LEVEL) if level_name else _DEFAULT_LEVEL

    if stream is None:
        stream = sys.stderr

    # Reset handlers so repeated calls don't accumulate them.
    for h in list(logger.handlers):
        logger.removeHandler(h)

    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    _configured = True
