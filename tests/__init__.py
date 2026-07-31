"""
Re-exports project paths so individual test files can
``from tests import REPO_ROOT, FIXTURES`` without redefining them.

Replaces the duplicated ``REPO_ROOT = Path(__file__).resolve().parents[1]``
lines that lived in 8 test files before Sprint 8 TD-2.

Fixtures live at the project root (``<repo>/fixtures/``), not inside
``tests/`` — the historical ``tests/fixtures/`` directory was a
duplicate that is no longer needed (verified via the consolidation in TD-2).
"""

from pathlib import Path

# Project root (one level up from the tests/ directory).
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Canonical fixtures location at the project root.
FIXTURES: Path = REPO_ROOT / "fixtures"

__all__ = ["REPO_ROOT", "FIXTURES"]
