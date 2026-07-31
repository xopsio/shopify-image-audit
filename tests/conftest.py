"""
Shared pytest fixtures and constants (Sprint 8, TD-2).

Replaces per-file duplications of:
- ``REPO_ROOT = Path(__file__).resolve().parents[1]``
- ``FIXTURES = REPO_ROOT / "fixtures"``
- ``sys.path.insert(0, str(REPO_ROOT / "src"))`` (no longer needed;
  ``pyproject.toml`` sets ``pythonpath = ["src"]``)
- ``AuditResult.model_validate({...})`` sample fixtures (5 duplicates)

The project-root ``fixtures/`` directory is the canonical location; the
older ``tests/fixtures/`` is consolidated into the same path. ``test_core``
continues to expose ``FIXTURES`` as the project-root path — the prior
``tests/fixtures/`` reference is corrected here.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from audit.models import AuditResult
from engine.history import HistoryStore

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FIXTURES: Path = REPO_ROOT / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the top-level ``fixtures/`` directory."""
    return FIXTURES


@pytest.fixture
def cli_runner() -> Iterator[CliRunner]:
    """Module-scoped (per-function) CLI runner for ``app``.

    Each test gets a fresh runner. Typer's ``CliRunner.invoke`` doesn't
    share global state between calls, so a per-function fixture is
    sufficient.
    """
    runner = CliRunner()
    yield runner


@pytest.fixture
def sample_audit_result() -> AuditResult:
    """A representative ``AuditResult`` for assertions / fixtures.

    Replaces the 5 hand-coded duplicates in
    ``tests/test_history.py``, ``tests/test_history_diff.py``,
    ``tests/test_scheduler.py``.
    """
    return AuditResult.model_validate({
        "meta": {
            "url": "https://demo.myshopify.com",
            "timestamp_utc": "2026-07-30T15:00:00Z",
            "device": "mobile", "runs": 1, "tool": "lighthouse",
        },
        "vitals": {"lcp_ms": 1800.0, "cls": 0.05, "inp_ms": 120.0, "ttfb_ms": 400.0},
        "images": [
            {
                "src": "https://cdn.example.com/hero.jpg", "role": "hero",
                "score": 80, "bytes": 95_000, "mime": "image/webp",
                "is_lcp_candidate": True,
                "waste_bytes_est": 10_000,
                "recommendation": "Convert to WebP",
            },
        ],
        "summary": {"top_issues": []},
    })


@pytest.fixture
def populated_history_dir(tmp_path: Path) -> tuple[Path, HistoryStore]:
    """A pre-populated ``HistoryStore`` in a tmp directory.

    Returns ``(tmp_path, store)``. Use ``store`` to introspect or
    extend; ``tmp_path`` is the underlying filesystem location.
    """
    store = HistoryStore(base_dir=tmp_path)
    return tmp_path, store
