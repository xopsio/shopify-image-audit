"""
Model & pipeline integration tests.
Tests that parser → ranker → AuditResult.model_validate works end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audit.models import AuditResult, ImageItem, ImageRole, Meta, Vitals
from audit.parser import parse_file
from audit.ranker_heuristic import rank
from engine.audit_orchestrator import run_audit

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "fixtures"


# ---------------------------------------------------------------------------
# Pipeline integration (parse → rank → validate)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["bad_hero_lcp.json", "optimized_shopify.json"])
def test_fixture_pipeline(name: str) -> None:
    """Full pipeline: parse_file → rank → run_audit → AuditResult validated."""
    path = FIXTURES / name
    assert path.exists(), f"Missing fixture: {path}"

    # parser returns list[dict]
    parsed = parse_file(str(path))
    assert isinstance(parsed, list) and len(parsed) > 0

    # ranker returns list[dict] with role/score/recommendation added
    ranked = rank(parsed)
    assert isinstance(ranked, list) and len(ranked) > 0

    for img in ranked:
        assert isinstance(img.get("src", ""), str) and img.get("src")
        score = int(img.get("score", 0))
        assert 0 <= score <= 100
        assert isinstance(img.get("role", ""), str)
        assert isinstance(img.get("recommendation", ""), str)

    assert any(bool(i.get("is_lcp_candidate", False)) for i in ranked)

    # orchestrator returns validated AuditResult
    result = run_audit(path)
    assert isinstance(result, AuditResult)
    assert len(result.images) > 0


# ---------------------------------------------------------------------------
# Pydantic model unit tests
# ---------------------------------------------------------------------------

class TestImageRole:
    def test_all_roles_defined(self) -> None:
        expected = {"hero", "above_fold", "product_primary", "product_secondary", "decorative", "unknown"}
        assert {r.value for r in ImageRole} == expected


class TestMeta:
    def test_valid_meta(self) -> None:
        m = Meta(url="https://example.com", timestamp_utc="2026-03-06T00:00:00Z",
                 device="mobile", runs=1, tool="lighthouse")
        assert m.url == "https://example.com"

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(Exception):
            Meta(url="https://x.com", timestamp_utc="2026-03-06T00", device="mobile",
                 runs=1, tool="lighthouse", bogus="nope")


class TestVitals:
    def test_valid_vitals(self) -> None:
        v = Vitals(lcp_ms=1200.0, cls=0.05, inp_ms=100.0, ttfb_ms=300.0)
        assert v.lcp_ms == 1200.0

    def test_rejects_negative(self) -> None:
        with pytest.raises(Exception):
            Vitals(lcp_ms=-1, cls=0, inp_ms=0, ttfb_ms=0)


class TestImageItem:
    def test_valid_image(self) -> None:
        img = ImageItem(src="https://cdn.shopify.com/img.webp", role="hero",
                        score=85, bytes=95000, mime="image/webp")
        assert img.role == ImageRole.hero

    def test_rejects_score_over_100(self) -> None:
        with pytest.raises(Exception):
            ImageItem(src="x", role="hero", score=101, bytes=0, mime="image/jpeg")


class TestAuditResult:
    def test_rejects_extra_top_level(self) -> None:
        with pytest.raises(Exception):
            AuditResult.model_validate({
                "meta": {"url": "x", "timestamp_utc": "2026-03-06T00", "device": "mobile", "runs": 1, "tool": "lighthouse"},
                "vitals": {"lcp_ms": 0, "cls": 0, "inp_ms": 0, "ttfb_ms": 0},
                "images": [],
                "summary": {"top_issues": []},
                "extra_field": "should_fail",
            })
