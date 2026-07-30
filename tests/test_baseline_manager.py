"""
Unit tests for ``src/core/baseline_manager.py`` — the before/after comparison
engine (Sprint 2, #18).

Covers: baseline save/load roundtrip, delta calculation (both directions),
status derivation, ROI heuristic, image aggregate deltas, and edge cases
(empty images, zero before-value, unchanged metrics).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from audit.models import AuditResult, ComparisonResult
from core.baseline_manager import (
    _delta,
    _image_key,
    _match_images,
    _per_image_recommendation,
    _per_image_status,
    _roi_estimate,
    _strip_query_params,
    compare,
    load_baseline,
    save_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BEFORE_AFTER = REPO_ROOT / "fixtures" / "before_after"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def before_result() -> AuditResult:
    import sys
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from engine.audit_orchestrator import run_audit
    return run_audit(BEFORE_AFTER / "before_lcp.json", url="https://demo.myshopify.com")


@pytest.fixture(scope="module")
def after_result() -> AuditResult:
    import sys
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from engine.audit_orchestrator import run_audit
    return run_audit(BEFORE_AFTER / "after_lcp.json", url="https://demo.myshopify.com")


# ---------------------------------------------------------------------------
# _delta helper
# ---------------------------------------------------------------------------

class TestDelta:
    def test_improvement_lower_is_better(self) -> None:
        d = _delta(4000, 2000, lower_is_better=True)
        assert d.delta == -2000
        assert d.status == "improved"

    def test_regression_lower_is_better(self) -> None:
        d = _delta(2000, 4000, lower_is_better=True)
        assert d.delta == 2000
        assert d.status == "regressed"

    def test_unchanged_within_tolerance(self) -> None:
        d = _delta(2000, 2000 + 1e-9, lower_is_better=True)
        assert d.status == "unchanged"

    def test_delta_pct_relative_to_before(self) -> None:
        d = _delta(4000, 2000, lower_is_better=True)
        assert d.delta_pct == pytest.approx(-50.0)

    def test_delta_pct_none_when_before_zero(self) -> None:
        d = _delta(0, 100, lower_is_better=True)
        assert d.delta_pct is None
        # status still derivable
        assert d.status == "regressed"

    def test_higher_is_better_inverts_status(self) -> None:
        d = _delta(50, 80, lower_is_better=False)
        assert d.status == "improved"
        d2 = _delta(80, 50, lower_is_better=False)
        assert d2.status == "regressed"


# ---------------------------------------------------------------------------
# save_baseline / load_baseline
# ---------------------------------------------------------------------------

class TestSaveLoadBaseline:
    def test_roundtrip_preserves_data(self, tmp_path: Path, before_result: AuditResult) -> None:
        path = tmp_path / "baseline.json"
        save_baseline(before_result, path)
        assert path.exists()
        loaded = load_baseline(path)
        assert loaded.meta.url == before_result.meta.url
        assert loaded.vitals.lcp_ms == before_result.vitals.lcp_ms
        assert len(loaded.images) == len(before_result.images)

    def test_save_creates_parent_dirs(self, tmp_path: Path, before_result: AuditResult) -> None:
        path = tmp_path / "nested" / "dir" / "baseline.json"
        result = save_baseline(before_result, path)
        assert result == path
        assert path.exists()

    def test_save_returns_resolved_path(self, tmp_path: Path, before_result: AuditResult) -> None:
        path = save_baseline(before_result, tmp_path / "b.json")
        assert isinstance(path, Path)

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_baseline(tmp_path / "nope.json")

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        with pytest.raises(json.JSONDecodeError):
            load_baseline(bad)

    def test_load_non_auditresult_payload_raises(self, tmp_path: Path) -> None:
        # A raw fixture (not a validated AuditResult) must be rejected.
        bad = tmp_path / "raw.json"
        bad.write_text(json.dumps({"lcpCandidate": {"url": "x"}, "images": []}))
        with pytest.raises((ValidationError, ValueError)):
            load_baseline(bad)


# ---------------------------------------------------------------------------
# compare()
# ---------------------------------------------------------------------------

class TestCompare:
    def test_returns_comparison_result(self, before_result, after_result) -> None:
        comp = compare(before_result, after_result)
        assert isinstance(comp, ComparisonResult)

    def test_lcp_improvement_detected(self, before_result, after_result) -> None:
        comp = compare(before_result, after_result)
        # before 4200ms -> after 1800ms
        assert comp.vitals.lcp.before == 4200.0
        assert comp.vitals.lcp.after == 1800.0
        assert comp.vitals.lcp.delta == -2400.0
        assert comp.vitals.lcp.status == "improved"

    def test_all_vitals_present(self, before_result, after_result) -> None:
        comp = compare(before_result, after_result)
        for key in ("lcp", "cls", "inp", "ttfb"):
            assert hasattr(comp.vitals, key)

    def test_image_aggregate_deltas(self, before_result, after_result) -> None:
        comp = compare(before_result, after_result)
        assert comp.images.before_count == 3
        assert comp.images.after_count == 3
        # after payload is much smaller
        assert comp.images.total_bytes_delta < 0
        assert comp.images.avg_score_delta > 0  # scores improved

    def test_summary_lists_improvements(self, before_result, after_result) -> None:
        comp = compare(before_result, after_result)
        assert len(comp.summary.top_improvements) > 0
        # LCP improvement should be mentioned
        assert any("LCP" in i for i in comp.summary.top_improvements)

    def test_summary_empty_when_no_change(self, before_result) -> None:
        comp = compare(before_result, before_result)
        # All deltas zero -> single "no measurable changes" line, no regressions
        assert len(comp.summary.top_improvements) >= 1
        assert comp.summary.top_regressions == []

    def test_before_after_meta_captured(self, before_result, after_result) -> None:
        comp = compare(before_result, after_result)
        assert comp.before["url"] == "https://demo.myshopify.com"
        assert comp.after["url"] == "https://demo.myshopify.com"

    def test_accepts_dicts_too(self, before_result, after_result) -> None:
        """compare() should also accept model_dump() dicts, not just models."""
        comp = compare(before_result.model_dump(), after_result.model_dump())
        assert comp.vitals.lcp.status == "improved"

    def test_regression_detected_when_after_worse(self, before_result, after_result) -> None:
        # Swap: before is the better one
        comp = compare(after_result, before_result)
        assert comp.vitals.lcp.status == "regressed"
        assert len(comp.summary.top_regressions) > 0

    def test_empty_images(self) -> None:
        """compare() must not divide by zero when images lists are empty."""
        import sys
        sys.path.insert(0, str(REPO_ROOT / "src"))
        empty = {
            "meta": {"url": "x", "timestamp_utc": "2026-01-01T00:00:00Z",
                     "device": "mobile", "runs": 1, "tool": "lighthouse"},
            "vitals": {"lcp_ms": 1000.0, "cls": 0.0, "inp_ms": 100.0, "ttfb_ms": 200.0},
            "images": [],
            "summary": {"top_issues": []},
        }
        comp = compare(empty, empty)
        assert comp.images.before_count == 0
        assert comp.images.avg_score_delta == 0.0


# ---------------------------------------------------------------------------
# ROI heuristic
# ---------------------------------------------------------------------------

class TestRoiEstimate:
    def test_large_lcp_improvement_gives_uplift(self, before_result, after_result) -> None:
        comp = compare(before_result, after_result)
        # 2400ms improvement -> ~24% estimate
        assert "24%" in comp.summary.roi_estimate
        assert "conversion" in comp.summary.roi_estimate.lower()

    def test_no_lcp_change_gives_neutral_message(self) -> None:
        import sys
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from audit.models import ImageStatsDelta, MetricDelta, VitalsDelta
        vd = VitalsDelta(
            lcp=MetricDelta(before=1000, after=1000, delta=0, delta_pct=0, status="unchanged"),
            cls=MetricDelta(before=0, after=0, delta=0, status="unchanged"),
            inp=MetricDelta(before=0, after=0, delta=0, status="unchanged"),
            ttfb=MetricDelta(before=0, after=0, delta=0, status="unchanged"),
        )
        isd = ImageStatsDelta(
            before_count=0, after_count=0, count_delta=0,
            before_total_bytes=0, after_total_bytes=0, total_bytes_delta=0,
            before_total_waste=0, after_total_waste=0, total_waste_delta=0,
            before_avg_score=0, after_avg_score=0, avg_score_delta=0,
        )
        msg = _roi_estimate(vd, isd)
        assert "No significant LCP change" in msg


# ---------------------------------------------------------------------------
# Per-image deltas (Sprint 3, TD-2)
# ---------------------------------------------------------------------------

class TestStripQueryParams:
    def test_no_query(self) -> None:
        assert _strip_query_params("https://cdn.example.com/hero.webp") == \
            "https://cdn.example.com/hero.webp"

    def test_with_v_query(self) -> None:
        assert _strip_query_params(
            "https://cdn.example.com/hero.webp?v=2"
        ) == "https://cdn.example.com/hero.webp"

    def test_with_multiple_params(self) -> None:
        assert _strip_query_params(
            "https://cdn.example.com/hero.webp?v=2&token=abc"
        ) == "https://cdn.example.com/hero.webp"

    def test_relative_path(self) -> None:
        assert _strip_query_params("/path/img.jpg?x=1") == "/path/img.jpg"


class TestImageKey:
    def test_same_input_same_key(self) -> None:
        img = {"src": "https://cdn.example.com/x.jpg", "bytes": 1000, "mime": "image/jpeg"}
        assert _image_key(img) == _image_key(dict(img))

    def test_query_param_does_not_change_key(self) -> None:
        # CDN cache busting must not break matching.
        a = {"src": "https://cdn.example.com/hero.webp", "bytes": 1000, "mime": "image/webp"}
        b = {"src": "https://cdn.example.com/hero.webp?v=2", "bytes": 1000, "mime": "image/webp"}
        assert _image_key(a) == _image_key(b)

    def test_different_bytes_different_key(self) -> None:
        a = {"src": "https://x/y.jpg", "bytes": 1000, "mime": "image/jpeg"}
        b = {"src": "https://x/y.jpg", "bytes": 2000, "mime": "image/jpeg"}
        assert _image_key(a) != _image_key(b)

    def test_different_mime_different_key(self) -> None:
        a = {"src": "https://x/y", "bytes": 1000, "mime": "image/jpeg"}
        b = {"src": "https://x/y", "bytes": 1000, "mime": "image/webp"}
        assert _image_key(a) != _image_key(b)


class TestPerImageStatus:
    @pytest.mark.parametrize("before,after,expected", [
        (1000, 500, "improved"),     # -50% >= 10% threshold
        (1000, 700, "improved"),     # -30% >= 10% threshold
        (1000, 950, "unchanged"),    # -5% within tolerance
        (1000, 1050, "unchanged"),   # +5% within tolerance
        (1000, 2000, "regressed"),   # +100% >= 10% threshold
        (0, 1000, "unchanged"),      # zero before_bytes -> unchanged (can't compute ratio)
    ])
    def test_status_thresholds(self, before, after, expected) -> None:
        assert _per_image_status(before, after) == expected


class TestPerImageRecommendation:
    def test_added_recommends_webp(self) -> None:
        rec = _per_image_recommendation("added", None, "image/jpeg", 0)
        assert "WebP" in rec or "AVIF" in rec

    def test_added_no_recommendation_for_modern_format(self) -> None:
        rec = _per_image_recommendation("added", None, "image/webp", 0)
        assert "WebP" not in rec  # already modern

    def test_removed_short(self) -> None:
        assert _per_image_recommendation("removed", "image/jpeg", None, 0) == "Image removed."

    def test_format_conversion_mentions_both(self) -> None:
        rec = _per_image_recommendation(
            "improved", "image/jpeg", "image/webp", 5,
        )
        assert "jpeg" in rec.lower() and "webp" in rec.lower()


class TestMatchImages:
    def test_empty_inputs(self) -> None:
        assert _match_images([], []) == []

    def test_perfect_match(self) -> None:
        """Same src (with different cache-bust query params) and same bytes/mime -> paired."""
        before = [{"src": "https://x/a.jpg", "bytes": 1000, "mime": "image/jpeg"}]
        after = [{"src": "https://x/a.jpg?v=2", "bytes": 1000, "mime": "image/jpeg"}]
        deltas = _match_images(before, after)
        assert len(deltas) == 1
        assert deltas[0].before == before[0]
        assert deltas[0].after == after[0]
        assert deltas[0].bytes_delta == 0
        assert deltas[0].status == "unchanged"

    def test_size_reduction_is_improved(self) -> None:
        before = [{"src": "https://x/hero.jpg", "bytes": 1_200_000, "mime": "image/jpeg"}]
        after = [{"src": "https://x/hero.webp", "bytes": 95_000, "mime": "image/webp"}]
        deltas = _match_images(before, after)
        # Different bytes+mime -> different _image_key -> "removed" + "added"
        # NOT "improved" (which requires same key). This is by design: format
        # conversion IS a new image.
        statuses = {d.status for d in deltas}
        assert statuses == {"removed", "added"}

    def test_added_only(self) -> None:
        deltas = _match_images(
            [],
            [{"src": "https://x/new.jpg", "bytes": 500, "mime": "image/jpeg"}],
        )
        assert len(deltas) == 1
        assert deltas[0].status == "added"
        assert deltas[0].before is None
        assert deltas[0].after is not None

    def test_removed_only(self) -> None:
        deltas = _match_images(
            [{"src": "https://x/old.jpg", "bytes": 1000, "mime": "image/jpeg"}],
            [],
        )
        assert len(deltas) == 1
        assert deltas[0].status == "removed"
        assert deltas[0].before is not None
        assert deltas[0].after is None

    def test_mixed_add_remove_keep(self) -> None:
            """3 before, 3 after: 1 kept, 1 removed (no match), 1 added, 1 regressed (5x growth)."""
            before = [
                {"src": "https://x/keep.jpg", "bytes": 1000, "mime": "image/jpeg"},
                {"src": "https://x/removed.jpg", "bytes": 2000, "mime": "image/jpeg"},
                {"src": "https://x/grew.jpg", "bytes": 100, "mime": "image/jpeg"},
            ]
            after = [
                {"src": "https://x/keep.jpg", "bytes": 1000, "mime": "image/jpeg"},
                {"src": "https://x/grew.jpg", "bytes": 500, "mime": "image/jpeg"},
                {"src": "https://x/added.jpg", "bytes": 300, "mime": "image/webp"},
            ]
            deltas = _match_images(before, after)
            statuses = {d.status for d in deltas}
            # keep: unchanged (same bytes); removed: removed (no after-match);
            # grew: regressed (bytes 100 -> 500 = +400%); added: added
            assert statuses == {"added", "removed", "regressed", "unchanged"}


class TestComparePerImage:
    """The compare() function must populate the new per_image field."""

    def test_compare_populates_per_image(self) -> None:
        before = AuditResult.model_validate({
            "meta": {"url": "x", "timestamp_utc": "2026-01-01T00:00:00Z",
                     "device": "mobile", "runs": 1, "tool": "lighthouse"},
            "vitals": {"lcp_ms": 1000.0, "cls": 0.0, "inp_ms": 100.0, "ttfb_ms": 200.0},
            "images": [
                {"src": "https://x/hero.jpg", "role": "hero", "score": 50,
                 "bytes": 500_000, "mime": "image/jpeg"},
            ],
            "summary": {"top_issues": []},
        })
        after = AuditResult.model_validate({
            "meta": {"url": "y", "timestamp_utc": "2026-01-02T00:00:00Z",
                     "device": "mobile", "runs": 1, "tool": "lighthouse"},
            "vitals": {"lcp_ms": 1000.0, "cls": 0.0, "inp_ms": 100.0, "ttfb_ms": 200.0},
            "images": [
                {"src": "https://x/hero.jpg?v=2", "role": "hero", "score": 90,
                 "bytes": 500_000, "mime": "image/jpeg"},
            ],
            "summary": {"top_issues": []},
        })
        comp = compare(before, after)
        assert len(comp.per_image) == 1
        assert comp.per_image[0].status == "unchanged"
        assert comp.per_image[0].score_delta == 40

    def test_compare_empty_images_yields_empty_per_image(self) -> None:
        before = AuditResult.model_validate({
            "meta": {"url": "x", "timestamp_utc": "2026-01-01T00:00:00Z",
                     "device": "mobile", "runs": 1, "tool": "lighthouse"},
            "vitals": {"lcp_ms": 1000.0, "cls": 0.0, "inp_ms": 100.0, "ttfb_ms": 200.0},
            "images": [],
            "summary": {"top_issues": []},
        })
        after = before.model_copy(deep=True)
        after.meta.url = "y"
        after.meta.timestamp_utc = "2026-01-02T00:00:00Z"
        comp = compare(before, after)
        assert comp.per_image == []

    def test_compare_preserves_cohort_aggregates(self) -> None:
        """Adding per_image must not remove the existing cohort-level fields."""
        before = AuditResult.model_validate({
            "meta": {"url": "x", "timestamp_utc": "2026-01-01T00:00:00Z",
                     "device": "mobile", "runs": 1, "tool": "lighthouse"},
            "vitals": {"lcp_ms": 1000.0, "cls": 0.0, "inp_ms": 100.0, "ttfb_ms": 200.0},
            "images": [
                {"src": "a.jpg", "role": "hero", "score": 80, "bytes": 1000, "mime": "image/jpeg"},
            ],
            "summary": {"top_issues": []},
        })
        after = AuditResult.model_validate({
            "meta": {"url": "y", "timestamp_utc": "2026-01-02T00:00:00Z",
                     "device": "mobile", "runs": 1, "tool": "lighthouse"},
            "vitals": {"lcp_ms": 1000.0, "cls": 0.0, "inp_ms": 100.0, "ttfb_ms": 200.0},
            "images": [
                {"src": "a.jpg", "role": "hero", "score": 90, "bytes": 800, "mime": "image/jpeg"},
            ],
            "summary": {"top_issues": []},
        })
        comp = compare(before, after)
        # Cohort fields still populated (backward compat)
        assert comp.images.before_total_bytes == 1000
        assert comp.images.after_total_bytes == 800
        # AND per_image is populated
        assert len(comp.per_image) == 1
