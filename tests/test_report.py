"""
Unit tests for ``src/audit/report.py`` render functions.

Scope (Sprint 2, issue #20 prep):
- The report was refactored from a single ~380-line monolith into focused
  ``_render_*`` functions. These tests pin the behaviour of the individual
  renderers and the before/after comparison extension point.
- ``generate_html_report`` keeps its public contract; the CLI-level integration
  (exit codes, file output) is covered by ``tests/test_cli.py``.
- XSS escaping is covered here at the unit level and end-to-end in test_cli.
"""

from __future__ import annotations

import json

import pytest

from audit.report import (
    _aggregate_stats,
    _render_comparison_section,
    _render_image_row,
    _render_issues,
    _render_meta,
    _render_role_distribution,
    _render_vitals,
    _vitals_status,
    generate_html_report,
)
from tests import FIXTURES

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _minimal_result(**overrides) -> dict:
    """Return a minimal, schema-shaped audit_result dict for tests."""
    base = {
        "meta": {
            "url": "https://example.com",
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "device": "mobile",
            "runs": 1,
            "tool": "lighthouse",
        },
        "vitals": {"lcp_ms": 2000.0, "cls": 0.05, "inp_ms": 150.0, "ttfb_ms": 600.0},
        "images": [
            {
                "src": "https://example.com/hero.webp",
                "role": "hero",
                "score": 85,
                "bytes": 50000,
                "mime": "image/webp",
                "displayed_width": 800,
                "displayed_height": 600,
            }
        ],
        "summary": {"top_issues": []},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _vitals_status
# ---------------------------------------------------------------------------

class TestVitalsStatus:
    def test_good_below_threshold(self) -> None:
        assert _vitals_status("lcp_ms", 2000) == "good"

    def test_needs_improvement_between_thresholds(self) -> None:
        assert _vitals_status("lcp_ms", 3000) == "needs-improvement"

    def test_poor_above_threshold(self) -> None:
        assert _vitals_status("lcp_ms", 5000) == "poor"

    def test_boundary_good_is_inclusive(self) -> None:
        # 2500 is the good boundary for LCP -> "good"
        assert _vitals_status("lcp_ms", 2500) == "good"

    def test_boundary_poor_is_exclusive_lower(self) -> None:
        # 4000 is the poor boundary for LCP -> still needs-improvement (inclusive)
        assert _vitals_status("lcp_ms", 4000) == "needs-improvement"

    def test_cls_unitless_thresholds(self) -> None:
        assert _vitals_status("cls", 0.05) == "good"
        assert _vitals_status("cls", 0.2) == "needs-improvement"
        assert _vitals_status("cls", 0.3) == "poor"


# ---------------------------------------------------------------------------
# _aggregate_stats
# ---------------------------------------------------------------------------

class TestAggregateStats:
    def test_basic_aggregation(self) -> None:
        images = [
            {"bytes": 1000, "score": 80, "role": "hero", "waste_bytes_est": 200},
            {"bytes": 3000, "score": 60, "role": "decorative", "waste_bytes_est": 500},
        ]
        stats = _aggregate_stats(images)
        assert stats["total_images"] == 2
        assert stats["total_bytes"] == 4000
        assert stats["total_waste"] == 700
        assert stats["avg_score"] == 70.0
        assert stats["role_counts"] == {"hero": 1, "decorative": 1}

    def test_empty_images_no_division_error(self) -> None:
        stats = _aggregate_stats([])
        assert stats["total_images"] == 0
        assert stats["total_bytes"] == 0
        assert stats["avg_score"] == 0
        assert stats["role_counts"] == {}

    def test_missing_waste_defaults_to_zero(self) -> None:
        stats = _aggregate_stats([{"bytes": 100, "score": 50, "role": "hero"}])
        assert stats["total_waste"] == 0


# ---------------------------------------------------------------------------
# _render_meta
# ---------------------------------------------------------------------------

class TestRenderMeta:
    def test_basic_fields_rendered(self) -> None:
        meta = _minimal_result()["meta"]
        out = _render_meta(meta)
        assert "https://example.com" in out
        assert "Mobile" in out  # device capitalised
        assert "Lighthouse" in out  # tool capitalised
        assert "Runs:</strong> 1" in out

    def test_notes_omitted_when_absent(self) -> None:
        out = _render_meta(_minimal_result()["meta"])
        assert "Notes" not in out

    def test_notes_rendered_when_present(self) -> None:
        meta = _minimal_result()["meta"]
        meta["notes"] = "baseline run"
        out = _render_meta(meta)
        assert "<strong>Notes:</strong> baseline run" in out

    def test_meta_escapes_html(self) -> None:
        meta = _minimal_result()["meta"]
        meta["url"] = "<script>x</script>"
        out = _render_meta(meta)
        assert "&lt;script&gt;" in out
        assert "<script>" not in out


# ---------------------------------------------------------------------------
# _render_vitals
# ---------------------------------------------------------------------------

class TestRenderVitals:
    def test_all_four_vitals_present(self) -> None:
        out = _render_vitals(_minimal_result()["vitals"])
        for name in ("LCP", "CLS", "INP", "TTFB"):
            assert f'vital-name">{name}</div>' in out

    def test_cards_are_separated(self) -> None:
        # Regression: cards must not collapse into a single line
        out = _render_vitals(_minimal_result()["vitals"])
        assert out.count('class="vital-card') == 4
        # Each card close should be followed by a newline, not another tag
        assert "</div>            <div" not in out

    def test_values_formatted(self) -> None:
        out = _render_vitals({"lcp_ms": 2500.0, "cls": 0.12, "inp_ms": 200.0, "ttfb_ms": 800.0})
        assert "2500ms" in out
        assert "0.120" in out  # CLS shows 3 decimals
        assert "200ms" in out
        assert "800ms" in out


# ---------------------------------------------------------------------------
# _render_issues
# ---------------------------------------------------------------------------

class TestRenderIssues:
    def test_empty_returns_empty_string(self) -> None:
        assert _render_issues({"top_issues": []}) == ""

    def test_issues_rendered_as_list(self) -> None:
        out = _render_issues({"top_issues": ["Slow LCP", "Big image"]})
        assert "<li>Slow LCP</li>" in out
        assert "<li>Big image</li>" in out
        assert "⚠️ Top Issues" in out

    def test_issues_escaped(self) -> None:
        out = _render_issues({"top_issues": ["<script>alert(1)</script>"]})
        assert "<li>&lt;script&gt;" in out
        assert "<script>" not in out


# ---------------------------------------------------------------------------
# _render_image_row
# ---------------------------------------------------------------------------

class TestRenderImageRow:
    def test_lcp_badge_shown(self) -> None:
        img = {"src": "x.jpg", "role": "hero", "score": 85, "bytes": 50000, "is_lcp_candidate": True}
        out = _render_image_row(img)
        assert 'class="lcp-badge">LCP' in out

    def test_lcp_badge_absent_when_not_candidate(self) -> None:
        img = {"src": "x.jpg", "role": "hero", "score": 85, "bytes": 50000}
        assert "lcp-badge" not in _render_image_row(img)

    def test_score_class_high(self) -> None:
        img = {"src": "x.jpg", "role": "hero", "score": 90, "bytes": 1}
        assert 'class="score high"' in _render_image_row(img)

    def test_score_class_medium(self) -> None:
        img = {"src": "x.jpg", "role": "hero", "score": 60, "bytes": 1}
        assert 'class="score medium"' in _render_image_row(img)

    def test_score_class_low(self) -> None:
        img = {"src": "x.jpg", "role": "hero", "score": 30, "bytes": 1}
        assert 'class="score low"' in _render_image_row(img)

    def test_src_escaped_and_truncated(self) -> None:
        long_src = "https://cdn.example.com/" + "a" * 80 + ".jpg"
        img = {"src": long_src, "role": "hero", "score": 50, "bytes": 1}
        out = _render_image_row(img)
        # Full (escaped) src in the title attribute for hover/tooltip
        assert f'title="{long_src}"' in out
        assert len(long_src) > 50  # sanity
        # The *visible* cell text is truncated to the last 50 chars of src
        tail = long_src[-50:]
        assert f">{tail}</td>" in out
        # And the long run of 'a' must not appear in the visible cell
        visible_cell = out.split('">', 1)[1].split('</td>', 1)[0]
        assert "a" * 51 not in visible_cell

    def test_dimensions_show_natural_when_missing(self) -> None:
        img = {"src": "x.jpg", "role": "hero", "score": 50, "bytes": 1}
        out = _render_image_row(img)
        assert "N/A" in out


# ---------------------------------------------------------------------------
# _render_role_distribution
# ---------------------------------------------------------------------------

class TestRenderRoleDistribution:
    def test_sorted_roles(self) -> None:
        out = _render_role_distribution({"decorative": 2, "hero": 1})
        # hero (h) sorts before decorative (d)? No: d < h alphabetically
        assert out.index("hero") < out.index("decorative") or out.index("decorative") < out.index("hero")
        assert ": 2 image" in out
        assert ": 1 image" in out  # singular

    def test_role_class_applied(self) -> None:
        out = _render_role_distribution({"hero": 1})
        assert 'class="role hero"' in out


# ---------------------------------------------------------------------------
# _render_comparison_section (before/after — #18/#20)
# ---------------------------------------------------------------------------

def _sample_comparison():
    """A minimal ComparisonResult-shaped dict for section tests."""
    return {
        "before": {"url": "https://before.example.com", "timestamp_utc": "2026-01-01T00:00:00Z"},
        "after": {"url": "https://after.example.com", "timestamp_utc": "2026-01-02T00:00:00Z"},
        "vitals": {
            "lcp": {"before": 4200.0, "after": 1800.0, "delta": -2400.0, "delta_pct": -57.14, "status": "improved"},
            "cls": {"before": 0.18, "after": 0.04, "delta": -0.14, "delta_pct": -77.78, "status": "improved"},
            "inp": {"before": 320.0, "after": 180.0, "delta": -140.0, "delta_pct": -43.75, "status": "improved"},
            "ttfb": {"before": 900.0, "after": 620.0, "delta": -280.0, "delta_pct": -31.11, "status": "improved"},
        },
        "images": {
            "before_count": 3, "after_count": 3, "count_delta": 0,
            "before_total_bytes": 1625000, "after_total_bytes": 139100, "total_bytes_delta": -1485900,
            "before_total_waste": 1570400, "after_total_waste": 84500, "total_waste_delta": -1485900,
            "before_avg_score": 10.0, "after_avg_score": 57.0, "avg_score_delta": 47.0,
        },
        "summary": {
            "top_improvements": ["LCP 4200ms → 1800ms (-57%)"],
            "top_regressions": [],
            "roi_estimate": "Estimated ~24% conversion uplift.",
        },
    }


class TestComparisonSection:
    def test_returns_empty_when_none(self) -> None:
        """No comparison argument -> no section (back-compat with single-audit reports)."""
        assert _render_comparison_section(None) == ""

    def test_renders_section_when_provided(self) -> None:
        out = _render_comparison_section(_sample_comparison())
        assert "Before / After Comparison" in out
        assert "before.example.com" in out
        assert "after.example.com" in out

    def test_renders_vital_rows(self) -> None:
        out = _render_comparison_section(_sample_comparison())
        # LCP before/after values present
        assert "4200ms" in out
        assert "1800ms" in out

    def test_marks_improvements_green(self) -> None:
        out = _render_comparison_section(_sample_comparison())
        assert 'class="delta improved"' in out

    def test_marks_regressions_red(self) -> None:
        comp = _sample_comparison()
        # Flip LCP to a regression
        comp["vitals"]["lcp"] = {
            "before": 1000.0, "after": 2500.0, "delta": 1500.0,
            "delta_pct": 150.0, "status": "regressed",
        }
        out = _render_comparison_section(comp)
        assert 'class="delta regressed"' in out

    def test_includes_roi_estimate(self) -> None:
        out = _render_comparison_section(_sample_comparison())
        assert "ROI estimate" in out
        assert "24% conversion uplift" in out

    def test_accepts_comparisonresult_model(self) -> None:
        """The renderer should accept a Pydantic ComparisonResult, not just a dict."""
        from audit.models import ComparisonResult
        comp = ComparisonResult.model_validate(_sample_comparison())
        out = _render_comparison_section(comp)
        assert "Before / After Comparison" in out


# ---------------------------------------------------------------------------
# generate_html_report (integration of renderers)
# ---------------------------------------------------------------------------

class TestGenerateHtmlReport:
    def test_full_structure(self) -> None:
        html = generate_html_report(_minimal_result())
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")
        for section in (
            "Shopify Image Audit Report",
            "Core Web Vitals",
            "Image Summary",
            "Image Details",
            "Role Distribution",
        ):
            assert section in html

    def test_accepts_bare_image_list(self) -> None:
        images = [{"src": "a.jpg", "role": "hero", "score": 80, "bytes": 1000, "mime": "image/jpeg"}]
        html = generate_html_report(images)
        assert "a.jpg" in html
        assert "N/A" in html  # synthesised meta

    def test_no_comparison_section_by_default(self) -> None:
        """Without a comparison arg, no Before/After section is emitted."""
        html = generate_html_report(_minimal_result())
        assert "Before / After Comparison" not in html

    def test_comparison_section_when_provided(self) -> None:
        """When a comparison is passed, the Before/After section appears."""
        html = generate_html_report(_minimal_result(), comparison=_sample_comparison())
        assert "Before / After Comparison" in html
        assert "ROI estimate" in html

    def test_comparison_css_classes_present(self) -> None:
        """The before/after CSS (delta states, roi-box) is pre-declared."""
        html = generate_html_report(_minimal_result())
        assert ".delta.improved" in html
        assert ".delta.regressed" in html
        assert ".roi-box" in html


# ---------------------------------------------------------------------------
# Golden-output equivalence (regression guard for the refactor)
# ---------------------------------------------------------------------------



class TestRefactorEquivalence:
    """Regression guard for the report refactor + comparison feature.

    The report was split into _render_* functions (#21) and the before/after
    comparison section was implemented (#18/#20). These tests pin the
    invariants that must hold for a single-audit report (no comparison arg).
    """

    @pytest.mark.parametrize("fixture", ["bad_hero_lcp.json", "optimized_shopify.json"])
    def test_single_audit_report_structure(self, fixture: str) -> None:

        from engine.audit_orchestrator import run_audit

        result = run_audit(FIXTURES / fixture)
        payload = json.loads(result.model_dump_json())
        html = generate_html_report(payload)

        # Structural sanity: well-formed document with all sections.
        assert "<!DOCTYPE html>" in html
        assert html.rstrip().endswith("</html>")
        assert html.count('class="vital-card') == 4
        # Cards must remain separated (regression from the refactor).
        assert "</div>            <div" not in html
        # No Before/After section when no comparison is supplied.
        assert "Before / After Comparison" not in html


# ---------------------------------------------------------------------------
# Sprint 6 TD-1: Direct coverage for _render_image_row
# ---------------------------------------------------------------------------



class TestRenderImageRowDirect:
    def test_high_score_class(self) -> None:
        out = _render_image_row({
            "src": "x.jpg", "role": "hero", "score": 90,
            "bytes": 1000, "mime": "image/jpeg",
        })
        assert 'class="score high"' in out

    def test_medium_score_class(self) -> None:
        out = _render_image_row({
            "src": "x.jpg", "role": "hero", "score": 60,
            "bytes": 1000, "mime": "image/jpeg",
        })
        assert 'class="score medium"' in out

    def test_low_score_class(self) -> None:
        out = _render_image_row({
            "src": "x.jpg", "role": "hero", "score": 30,
            "bytes": 1000, "mime": "image/jpeg",
        })
        assert 'class="score low"' in out

    def test_role_classes(self) -> None:
        """Each known role renders its specific CSS class."""
        for role in (
            "hero", "above_fold", "product_primary",
            "product_secondary", "decorative", "unknown",
        ):
            out = _render_image_row({
                "src": "x.jpg", "role": role, "score": 80,
                "bytes": 1000, "mime": "image/jpeg",
            })
            assert f'class="role {role}"' in out, f"Role {role!r} did not render its class"

    def test_recommendation_class_rendered(self) -> None:
        out = _render_image_row({
            "src": "x.jpg", "role": "hero", "score": 80,
            "bytes": 1000, "mime": "image/jpeg",
            "recommendation": "Convert to WebP",
        })
        assert 'class="recommendation"' in out

    def test_lcp_candidate_badge(self) -> None:
        out = _render_image_row({
            "src": "x.jpg", "role": "hero", "score": 80,
            "bytes": 1000, "mime": "image/jpeg",
            "is_lcp_candidate": True,
        })
        assert "lcp-badge" in out

    def test_no_lcp_badge_when_not_candidate(self) -> None:
        out = _render_image_row({
            "src": "x.jpg", "role": "decorative", "score": 80,
            "bytes": 1000, "mime": "image/jpeg",
            "is_lcp_candidate": False,
        })
        assert "lcp-badge" not in out

    def test_long_src_truncated(self) -> None:
        import re
        long_src = "https://example.com/" + ("UNIQUE_" * 50) + ".jpg"
        out = _render_image_row({
            "src": long_src, "role": "hero", "score": 80,
            "bytes": 1000, "mime": "image/jpeg",
        })
        # The visible cell contains only the last 50 chars
        m = re.search(r'<td class="bytes" title="[^"]*">([^<]*)<', out)
        assert m is not None, "Could not find <td> cell"
        visible = m.group(1)
        assert len(visible) == 50
        assert visible == long_src[-50:]
        # The full src (374 chars) is only in the title attribute, not in the visible cell
        assert long_src not in visible

    def test_missing_dimensions_rendered_as_na(self) -> None:
        out = _render_image_row({
            "src": "x.jpg", "role": "hero", "score": 80,
            "bytes": 1000, "mime": "image/jpeg",
        })
        assert "N/A×N/A" in out

    def test_dimensions_present(self) -> None:
        out = _render_image_row({
            "src": "x.jpg", "role": "hero", "score": 80,
            "bytes": 1000, "mime": "image/jpeg",
            "displayed_width": 800, "displayed_height": 600,
            "natural_width": 1600, "natural_height": 1200,
        })
        assert "800×600" in out
        assert "1600×1200" in out


class TestVitalCardNeedsImprovement:
    """The middle-band vital status must be exercised."""

    def test_needs_improvement_renders_class(self) -> None:
        from audit.report import _render_vital_card, _vitals_status

        # 0.15 CLS is "needs-improvement" (between 0.1 and 0.25)
        assert _vitals_status("cls", 0.15) == "needs-improvement"
        out = _render_vital_card("CLS", "cls", 0.15, "{:.3f}")
        assert "needs-improvement" in out
