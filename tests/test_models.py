"""
Model & pipeline integration tests.
Tests that parser → ranker → AuditResult.model_validate works end-to-end.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from audit.models import AuditResult, ImageDelta, ImageItem, ImageRole, Meta, Vitals
from audit.parser import parse_file
from audit.ranker_heuristic import rank
from engine.audit_orchestrator import run_audit
from tests import FIXTURES

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
        m = Meta(
            url="https://example.com", timestamp_utc="2026-03-06T00:00:00Z", device="mobile", runs=1, tool="lighthouse"
        )
        assert m.url == "https://example.com"

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            Meta(
                url="https://x.com",
                timestamp_utc="2026-03-06T00",
                device="mobile",
                runs=1,
                tool="lighthouse",
                bogus="nope",
            )


class TestVitals:
    def test_valid_vitals(self) -> None:
        v = Vitals(lcp_ms=1200.0, cls=0.05, inp_ms=100.0, ttfb_ms=300.0)
        assert v.lcp_ms == 1200.0

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            Vitals(lcp_ms=-1, cls=0, inp_ms=0, ttfb_ms=0)


class TestImageItem:
    def test_valid_image(self) -> None:
        img = ImageItem(src="https://cdn.shopify.com/img.webp", role="hero", score=85, bytes=95000, mime="image/webp")
        assert img.role == ImageRole.hero

    def test_rejects_score_over_100(self) -> None:
        with pytest.raises(ValidationError):
            ImageItem(src="x", role="hero", score=101, bytes=0, mime="image/jpeg")


class TestAuditResult:
    def test_rejects_extra_top_level(self) -> None:
        with pytest.raises(ValidationError):
            AuditResult.model_validate(
                {
                    "meta": {
                        "url": "x",
                        "timestamp_utc": "2026-03-06T00",
                        "device": "mobile",
                        "runs": 1,
                        "tool": "lighthouse",
                    },
                    "vitals": {"lcp_ms": 0, "cls": 0, "inp_ms": 0, "ttfb_ms": 0},
                    "images": [],
                    "summary": {"top_issues": []},
                    "extra_field": "should_fail",
                }
            )


# ---------------------------------------------------------------------------
# ImageDelta (Sprint 14 schema tightening)
# ---------------------------------------------------------------------------


class TestImageDelta:
    def test_before_after_accept_imageitem_dicts(self) -> None:
        """before/after are now ImageItem models (Sprint 14)."""
        img_dict = {
            "src": "https://x/y.jpg",
            "bytes": 1000,
            "mime": "image/jpeg",
            "role": "hero",
            "score": 90,
        }
        delta = ImageDelta(
            match_key="key",
            src=img_dict["src"],
            status="improved",
            before=ImageItem.model_validate(img_dict),
            after=ImageItem.model_validate(img_dict),
        )
        assert isinstance(delta.before, ImageItem)
        assert isinstance(delta.after, ImageItem)
        assert delta.before.role == ImageRole.hero
        assert delta.after.score == 90

    def test_before_after_none_for_added_removed(self) -> None:
        """None is still valid (matches 'added' / 'removed' status)."""
        delta_added = ImageDelta(match_key="k", src="x.jpg", status="added", before=None, after=None)
        delta_removed = ImageDelta(match_key="k", src="x.jpg", status="removed", before=None, after=None)
        assert delta_added.before is None
        assert delta_removed.after is None

    def test_extra_key_on_imageitem_is_rejected(self) -> None:
        """extra='forbid' on ImageItem rejects unknown keys (Sprint 14 guarantee)."""
        bad = {
            "src": "https://x/y.jpg",
            "bytes": 1000,
            "mime": "image/jpeg",
            "role": "hero",
            "score": 90,
            "bogus_extra": "should_fail",
        }
        with pytest.raises(ValidationError, match="bogus_extra"):
            ImageItem.model_validate(bad)
