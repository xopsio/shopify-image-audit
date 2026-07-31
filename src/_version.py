"""
Shared package version helper.

The canonical version source is the installed distribution metadata (read
via :func:`importlib.metadata.version`), which works for both editable
installs (``pip install -e .``) and wheel installs from PyPI. As a
fallback (development checkouts without an installed metadata record),
the version is parsed from the adjacent ``pyproject.toml``. The final
fallback is the literal string ``"unknown"``.

This module is shipped as part of the top-level package set (it lives in
``src/`` next to ``audit/`` and ``engine/`` so ``packages.find`` picks
it up).
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_PACKAGE_NAME = "shopify-image-audit"


def get_version() -> str:
    """Return the installed package version.

    Order of resolution:
      1. ``importlib.metadata.version("shopify-image-audit")`` — works for
         all pip/pipx/wheel installs (the canonical path).
      2. Parse the adjacent ``pyproject.toml`` — fallback for development
         checkouts that have not been installed.
      3. ``"unknown"`` — last resort.
    """
    try:
        return version(_PACKAGE_NAME)
    except PackageNotFoundError:
        pass
    # Development checkout fallback.
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        import tomllib
        with open(pyproject, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except (FileNotFoundError, KeyError, ModuleNotFoundError):
        return "unknown"
