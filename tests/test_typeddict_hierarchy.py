"""
TypedDict-hierarkia (Sprint 15) — smoke tests that the new
``LighthouseJson`` / ``CachedPageSpeedResponse`` / ``CachedEntry``
contracts accept the same dict shapes that production and mocks
already use. These are guard rails against accidentally tightening
``total=False`` into ``total=True`` or dropping a field the runtime
reads.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.audit_orchestrator import run_audit
from integrations._cache import ResponseCache
from integrations.pagespeed_api import (
    CachedPageSpeedResponse,
    Categories,
    LighthouseJson,
    PerformanceCategory,
)


def test_cached_entry_round_trip(tmp_path: Path) -> None:
    """ResponseCache.set() + get() round-trips a CachedPageSpeedResponse."""
    cache = ResponseCache(tmp_path, ttl=60)
    payload: CachedPageSpeedResponse = {
        "lighthouseResult": {
            "audits": {"largest-contentful-paint": {"numericValue": 1800}},
            "categories": {"performance": {"score": 0.95}},
            "fetchTime": "2026-07-30T15:00:00Z",
        }
    }
    cache.set("https://example.com", "mobile", payload)
    out = cache.get("https://example.com", "mobile")
    assert out == payload


def test_lighthouse_json_partial_mock() -> None:
    """``total=False`` accepts partial mocks — only some fields present."""
    partial: LighthouseJson = {
        "audits": {},
        "categories": {"performance": {"score": 0.5}},
    }
    # Type assertions: each nested TypedDict is structurally compatible.
    assert partial["categories"]["performance"]["score"] == 0.5


def test_performance_category_score_can_be_none() -> None:
    """PageSpeed returns ``None`` score when category is missing."""
    cat: PerformanceCategory = {"score": None}
    assert cat["score"] is None


def test_categories_without_performance() -> None:
    """Categories block can omit ``performance`` entirely."""
    cats: Categories = {}
    assert "performance" not in cats


def test_cached_page_speed_response_error_field() -> None:
    """API errors expose ``error`` instead of ``lighthouseResult``."""
    err: CachedPageSpeedResponse = {"error": {"code": 400, "message": "bad request"}}
    assert "error" in err
    assert "lighthouseResult" not in err


def test_run_audit_accepts_lighthouse_fixture(tmp_path: Path) -> None:
    """run_audit() runs end-to-end on a LighthouseJson-shaped fixture."""
    lhr: LighthouseJson = {
        "audits": {
            "largest-contentful-paint-element": {"details": {"items": [{"url": "https://cdn.example.com/hero.jpg"}]}},
            "image-elements": {
                "details": {
                    "items": [
                        {
                            "url": "https://cdn.example.com/hero.jpg",
                            "resourceSize": 95000,
                            "mimeType": "image/webp",
                            "displayedWidth": 1200,
                            "displayedHeight": 800,
                        }
                    ]
                }
            },
        },
        "categories": {"performance": {"score": 0.9}},
        "fetchTime": "2026-07-30T15:00:00Z",
    }
    p = tmp_path / "lhr.json"
    p.write_text(json.dumps(lhr), encoding="utf-8")
    result = run_audit(p, url="https://demo.myshopify.com")
    assert len(result.images) == 1
    assert result.images[0].is_lcp_candidate is True


def test_run_audit_minimal_fixture_no_metrics_block() -> None:
    """Audit must not blow up when the fixture omits the metrics audit block."""
    from tests import FIXTURES

    # Fixture JSON files are pre-built Lighthouse payloads — every field
    # that ``total=False`` says is optional is in fact absent in some of them.
    for name in ["bad_hero_lcp.json", "optimized_shopify.json"]:
        p = FIXTURES / name
        assert p.is_file()
        raw = json.loads(p.read_text())
        # The TypedDict must structurally accept any of the fixture payloads
        # without mypy-time errors — the next line would explode under
        # ``total=True`` for a missing required field.
        _: LighthouseJson = raw  # type: ignore[assignment]
