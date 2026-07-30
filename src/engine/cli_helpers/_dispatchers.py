"""
CLI input dispatchers.

Convert raw CLI inputs (file paths, URLs) into ``AuditResult`` objects the
rest of the pipeline can use. Extracted from ``cli.py`` to keep the command
bodies thin and to make the dispatch logic reusable across commands.

These helpers do NOT print output and do NOT handle errors; callers are
responsible for catching exceptions and converting them to ``typer.Exit``
codes. This separation keeps the helpers testable in isolation.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from audit.models import AuditResult
from core.baseline_manager import load_baseline
from engine.audit_orchestrator import run_audit
from integrations.pagespeed_api import fetch_lighthouse_json


def load_or_audit_file(path: Path | str) -> AuditResult:
    """Return an ``AuditResult`` for the given path.

    Tries ``load_baseline`` first (treats the input as a saved AuditResult
    JSON); if that fails, runs the audit pipeline on it (treats the input
    as a raw Lighthouse / fixture report).
    """
    try:
        return load_baseline(path)
    except Exception:
        return run_audit(path)


def fetch_url_as_audit(url: str, *, strategy: str = "mobile",
                       api_key: str | None = None) -> AuditResult:
    """Fetch a live URL via PageSpeed API and run the audit pipeline on it.

    The PageSpeed API returns a ``lighthouseResult`` dict; we write it to a
    temp file (because ``run_audit`` takes a path), feed it through the
    pipeline, and clean up. The ``url`` and ``device`` are propagated to the
    resulting ``AuditResult.meta`` so the report reflects the live source.
    """
    lhr = fetch_lighthouse_json(url, strategy=strategy, api_key=api_key)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(lhr, fh)
        tmp_path = Path(fh.name)
    try:
        return run_audit(tmp_path, url=url, device=strategy)
    finally:
        tmp_path.unlink(missing_ok=True)
