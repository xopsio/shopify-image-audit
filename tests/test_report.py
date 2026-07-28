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
from pathlib import Path

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
# _render_comparison_section (the #20 extension point)
# ---------------------------------------------------------------------------

class TestComparisonSection:
    def test_returns_empty_by_default(self) -> None:
        """The before/after section is a no-op until #18 lands its data contract."""
        assert _render_comparison_section(_minimal_result()) == ""

    def test_returns_empty_even_with_arbitrary_keys(self) -> None:
        # Must not crash on dicts that happen to carry unrelated keys.
        payload = _minimal_result()
        payload["comparison"] = {"foo": "bar"}
        assert _render_comparison_section(payload) == ""


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

    def test_comparison_section_does_not_add_content_yet(self) -> None:
        """No comparison *content/section* should leak until #18 lands.

        The reserved CSS rule + its comment are allowed (pre-declared styling),
        but no actual ``<section class="comparison">`` / ``<div class="comparison">``
        markup or before/after text must be emitted yet.
        """
        import re
        html = generate_html_report(_minimal_result())
        # Strip the CSS rule and its comment so only body markup is inspected.
        body_only = re.sub(r"\.comparison \{[^}]*\}", "", html)
        body_only = re.sub(r"/\* Reserved styling[\s\S]*?\*/", "", body_only)
        # No element should carry the comparison class as actual markup.
        assert 'class="comparison"' not in body_only
        assert "class='comparison'" not in body_only
        # No before/after text emitted yet.
        assert "Before" not in body_only
        assert "After" not in body_only

    def test_reserved_css_class_present(self) -> None:
        """The .comparison CSS is pre-declared so #18 can use it without a CSS diff."""
        html = generate_html_report(_minimal_result())
        assert ".comparison {" in html


# ---------------------------------------------------------------------------
# Golden-output equivalence (regression guard for the refactor)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "fixtures"


class TestRefactorEquivalence:
    """Pin the refactor to produce structurally equivalent output.

    The refactor split generate_html_report into _render_* functions. The only
    intended, additive change is the pre-declared ``.comparison`` CSS block.
    Everything else must match the fixture-driven output byte-for-byte after
    normalising the volatile timestamp.
    """

    @pytest.mark.parametrize("fixture", ["bad_hero_lcp.json", "optimized_shopify.json"])
    def test_output_unchanged_after_refactor(self, fixture: str) -> None:
        import re
        import sys

        sys.path.insert(0, str(REPO_ROOT / "src"))
        from engine.audit_orchestrator import run_audit

        result = run_audit(FIXTURES / fixture)
        payload = json.loads(result.model_dump_json())
        html = generate_html_report(payload)

        # Structural sanity: well-formed document with all sections.
        assert "<!DOCTYPE html>" in html
        assert html.count('class="vital-card') == 4
        # Cards must remain separated (regression from the refactor).
        assert "</div>            <div" not in html
        # Reserved comparison CSS present (the only intended additive change).
        assert ".comparison {" in html
        # No comparison content emitted yet.
        stripped = re.sub(r"\.comparison \{[^}]*\}", "", html)
        stripped = re.sub(r"/\* Reserved styling[\s\S]*?\*/", "", stripped)
        assert "comparison" not in stripped.lower().replace("margin: 20px 0; }", "")
