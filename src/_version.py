"""
Shared package version helper.

Reads the version from ``pyproject.toml`` at runtime so there is a single
source of truth. Falls back to ``"unknown"`` when the file can't be read
(e.g. running from a wheel without ``pyproject.toml`` next to it).
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def get_version() -> str:
    """Read the package version from pyproject.toml at runtime."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        with open(pyproject, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (FileNotFoundError, KeyError):
        return "unknown"
