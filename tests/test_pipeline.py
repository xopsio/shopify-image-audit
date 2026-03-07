"""
End-to-end pipeline tests using fixtures.

Validates:
- parser returns list[dict]
- ranker adds role / score / recommendation
- AuditResult.model_validate succeeds on the assembled payload
- Basic field assertions (images > 0, score 0-100, is_lcp_candidate present, etc.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit.models import AuditResult
from audit.parser import parse
from audit.ranker_heuristic import rank
from engine.audit_orchestrator import run_audit

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "fixtures"


# ---------------------------------------------------------------------------
# parametrised fixture paths
# ---------------------------------------------------------------------------

@pytest.fixture(params=["bad_hero_lcp.json", "optimized_shopify.json"])
def fixture_path(request: pytest.FixtureRequest) -> Path:
    p = FIXTURES / request.param
    assert p.exists(), f"Missing fixture: {p}"
    return p


# ---------------------------------------------------------------------------
# parser tests
# ---------------------------------------------------------------------------

class TestParser:
    def test_parse_returns_list(self, fixture_path: Path) -> None:
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        result = parse(data)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_parsed_images_have_required_keys(self, fixture_path: Path) -> None:
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        for img in parse(data):
            assert "src" in img
            assert "bytes" in img
            assert "mime" in img

    def test_lcp_candidate_marked(self, fixture_path: Path) -> None:
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        images = parse(data)
        assert any(img.get("is_lcp_candidate") for img in images)


# ---------------------------------------------------------------------------
# ranker tests
# ---------------------------------------------------------------------------

class TestRanker:
    def test_rank_adds_fields(self, fixture_path: Path) -> None:
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        ranked = rank(parse(data))
        assert len(ranked) > 0
        for img in ranked:
            assert "role" in img
            assert "score" in img
            assert "recommendation" in img

    def test_scores_in_range(self, fixture_path: Path) -> None:
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        for img in rank(parse(data)):
            assert 0 <= img["score"] <= 100


# ---------------------------------------------------------------------------
# orchestrator / AuditResult validation
# ---------------------------------------------------------------------------

class TestOrchestrator:
    def test_run_audit_returns_audit_result(self, fixture_path: Path) -> None:
        result = run_audit(fixture_path)
        assert isinstance(result, AuditResult)

    def test_images_not_empty(self, fixture_path: Path) -> None:
        result = run_audit(fixture_path)
        assert len(result.images) > 0

    def test_image_scores_in_range(self, fixture_path: Path) -> None:
        result = run_audit(fixture_path)
        for img in result.images:
            assert 0 <= img.score <= 100

    def test_lcp_candidate_exists(self, fixture_path: Path) -> None:
        result = run_audit(fixture_path)
        assert any(img.is_lcp_candidate for img in result.images)

    def test_meta_fields(self, fixture_path: Path) -> None:
        result = run_audit(fixture_path)
        assert result.meta.device in ("mobile", "desktop")
        assert result.meta.tool == "lighthouse"
        assert result.meta.runs >= 1
        assert len(result.meta.url) > 0
        assert len(result.meta.timestamp_utc) >= 10

    def test_vitals_non_negative(self, fixture_path: Path) -> None:
        result = run_audit(fixture_path)
        assert result.vitals.lcp_ms >= 0
        assert result.vitals.cls >= 0
        assert result.vitals.inp_ms >= 0
        assert result.vitals.ttfb_ms >= 0

    def test_summary_has_issues(self, fixture_path: Path) -> None:
        result = run_audit(fixture_path)
        assert isinstance(result.summary.top_issues, list)
        assert len(result.summary.top_issues) > 0

    def test_model_dump_roundtrip(self, fixture_path: Path) -> None:
        """model_dump → model_validate roundtrip must succeed."""
        result = run_audit(fixture_path)
        payload = result.model_dump()
        roundtripped = AuditResult.model_validate(payload)
        assert roundtripped == result


# ---------------------------------------------------------------------------
# bad_hero_lcp specific
# ---------------------------------------------------------------------------

class TestBadHeroFixture:
    @pytest.fixture()
    def result(self) -> AuditResult:
        return run_audit(FIXTURES / "bad_hero_lcp.json")

    def test_hero_lcp_is_large(self, result: AuditResult) -> None:
        lcp_images = [i for i in result.images if i.is_lcp_candidate]
        assert len(lcp_images) == 1
        assert lcp_images[0].bytes > 500_000

    def test_hero_gets_low_score(self, result: AuditResult) -> None:
        lcp_images = [i for i in result.images if i.is_lcp_candidate]
        assert lcp_images[0].score < 50

    def test_summary_mentions_lcp(self, result: AuditResult) -> None:
        combined = " ".join(result.summary.top_issues).lower()
        assert "lcp" in combined or "large" in combined


# ---------------------------------------------------------------------------
# optimized_shopify specific
# ---------------------------------------------------------------------------

class TestOptimizedFixture:
    @pytest.fixture()
    def result(self) -> AuditResult:
        return run_audit(FIXTURES / "optimized_shopify.json")

    def test_all_scores_reasonable(self, result: AuditResult) -> None:
        for img in result.images:
            assert img.score >= 50, f"Unexpectedly low score for optimised image: {img.src}"

    def test_modern_formats(self, result: AuditResult) -> None:
        modern = {"image/webp", "image/avif", "image/svg+xml"}
        for img in result.images:
            assert img.mime in modern or img.score >= 60
