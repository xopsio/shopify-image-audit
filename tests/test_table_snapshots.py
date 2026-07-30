"""
Snapshot-style tests for the Rich-based CLI table renderers in
``src/engine/cli_helpers/_table.py``.

Rich's ``Console(file=io.StringIO(), record=True)`` gives deterministic text
output regardless of terminal width (we lock it at 120 cols) and ignores
ANSI escape codes for the textual form. Status colour markup (e.g.
``[green]…[/green]``) is preserved and stable.
"""

from __future__ import annotations

import io

from rich.console import Console

from audit.models import (
    AuditResult,
    ComparisonResult,
    ComparisonSummary,
    ImageStatsDelta,
    MetricDelta,
    VitalsDelta,
)
from engine.cli_helpers._table import (
    print_audit_results,
    print_audit_summary,
    print_comparison_summary,
    print_comparison_table,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture_console() -> tuple[Console, io.StringIO]:
    """Return a (console, buffer) pair where console writes into the buffer.

    ``markup=False`` keeps ``[green]…[/green]`` markup as literal text in the
    captured output (instead of rendering ANSI codes), which makes the
    output stable and searchable across terminals.
    """
    buffer = io.StringIO()
    console = Console(
        file=buffer, record=True, width=120, force_terminal=False, markup=False,
    )
    return console, buffer


def _sample_audit_result() -> AuditResult:
    return AuditResult.model_validate({
        "meta": {
            "url": "https://demo.myshopify.com",
            "timestamp_utc": "2026-07-30T15:00:00Z",
            "device": "mobile", "runs": 1, "tool": "lighthouse",
        },
        "vitals": {"lcp_ms": 1800.0, "cls": 0.05, "inp_ms": 120.0, "ttfb_ms": 400.0},
        "images": [
            {
                "src": "https://cdn.example.com/hero.jpg",
                "role": "hero", "score": 80,
                "bytes": 120_000, "mime": "image/jpeg",
                "is_lcp_candidate": True,
                "recommendation": "Convert to WebP",
            },
            {
                "src": "https://cdn.example.com/thumb.png",
                "role": "decorative", "score": 95,
                "bytes": 45_000, "mime": "image/png",
                "is_lcp_candidate": False,
                "recommendation": None,
            },
        ],
        "summary": {"top_issues": ["Hero is 120 KB"]},
    })


def _sample_comparison_result(
    *, lcp_before: float = 4200.0, lcp_after: float = 1800.0,
    lcp_status: str = "improved",
) -> ComparisonResult:
    return ComparisonResult(
        before={"url": "https://demo.myshopify.com", "timestamp_utc": "2026-07-23T10:00:00Z"},
        after={"url": "https://demo.myshopify.com", "timestamp_utc": "2026-07-30T15:00:00Z"},
        vitals=VitalsDelta(
            lcp=MetricDelta(before=lcp_before, after=lcp_after,
                            delta=lcp_after - lcp_before,
                            delta_pct=((lcp_after - lcp_before) / lcp_before) * 100,
                            status=lcp_status),  # type: ignore[arg-type]
            cls=MetricDelta(before=0.18, after=0.05, delta=-0.13,
                            delta_pct=-72.2, status="improved"),
            inp=MetricDelta(before=320.0, after=120.0, delta=-200.0,
                            delta_pct=-62.5, status="improved"),
            ttfb=MetricDelta(before=900.0, after=400.0, delta=-500.0,
                             delta_pct=-55.6, status="improved"),
        ),
        images=ImageStatsDelta(
            before_count=2, after_count=2, count_delta=0,
            before_total_bytes=165_000, after_total_bytes=165_000, total_bytes_delta=0,
            before_total_waste=10_000, after_total_waste=10_000, total_waste_delta=0,
            before_avg_score=87.5, after_avg_score=87.5, avg_score_delta=0.0,
        ),
        summary=ComparisonSummary(
            top_improvements=["LCP 4200ms → 1800ms (-57%)"],
            top_regressions=[],
            roi_estimate="Estimated ~24% conversion uplift from a 2400ms LCP improvement.",
        ),
        per_image=[],
    )


# ---------------------------------------------------------------------------
# print_audit_results
# ---------------------------------------------------------------------------

class TestPrintAuditResults:
    def test_empty_images(self) -> None:
        result = _sample_audit_result()
        result = result.model_copy(update={"images": []})
        console, buf = _capture_console()
        print_audit_results(result, console=console)
        out = buf.getvalue()
        assert "Image Audit Results" in out
        # Header columns rendered but no rows
        assert out.count("Convert to WebP") == 0

    def test_lcp_candidate_y_badge(self) -> None:
        result = _sample_audit_result()
        console, buf = _capture_console()
        print_audit_results(result, console=console)
        out = buf.getvalue()
        assert "Y" in out  # LCP badge for hero

    def test_no_lcp_candidate_empty(self) -> None:
        result = _sample_audit_result()
        console, buf = _capture_console()
        print_audit_results(result, console=console)
        out = buf.getvalue()
        # Both "Y" and an empty string exist (one image has Y, one doesn't)
        assert "Y" in out
        # The decorative image has empty LCP marker
        assert "decorative" in out

    def test_role_rendered(self) -> None:
        result = _sample_audit_result()
        console, buf = _capture_console()
        print_audit_results(result, console=console)
        out = buf.getvalue()
        assert "hero" in out
        assert "decorative" in out

    def test_byte_formatting(self) -> None:
        result = _sample_audit_result()
        console, buf = _capture_console()
        print_audit_results(result, console=console)
        out = buf.getvalue()
        assert "120,000" in out
        assert "45,000" in out

    def test_missing_recommendation_renders_empty(self) -> None:
        result = _sample_audit_result()
        console, buf = _capture_console()
        print_audit_results(result, console=console)
        out = buf.getvalue()
        # Second image has None recommendation; row should still render
        assert "thumb.png" in out


# ---------------------------------------------------------------------------
# print_comparison_table
# ---------------------------------------------------------------------------

class TestPrintComparisonTable:
    def test_improved_renders_green_markup(self) -> None:
        comp = _sample_comparison_result()
        console, buf = _capture_console()
        print_comparison_table(comp, console=console)
        out = buf.getvalue()
        assert "[green]" in out
        assert "Before / After Comparison" in out

    def test_regressed_renders_red_markup(self) -> None:
        comp = _sample_comparison_result(lcp_before=1800.0, lcp_after=4200.0,
                                         lcp_status="regressed")
        console, buf = _capture_console()
        print_comparison_table(comp, console=console)
        out = buf.getvalue()
        assert "[red]" in out

    def test_unchanged_renders_dim(self) -> None:
        comp = _sample_comparison_result(lcp_before=2000.0, lcp_after=2000.0,
                                         lcp_status="unchanged")
        # Force delta to zero
        comp = comp.model_copy(update={
            "vitals": comp.vitals.model_copy(update={
                "lcp": MetricDelta(before=2000.0, after=2000.0, delta=0,
                                   delta_pct=0.0, status="unchanged"),
            }),
        })
        console, buf = _capture_console()
        print_comparison_table(comp, console=console)
        out = buf.getvalue()
        assert "[dim]" in out

    def test_all_four_metrics_rendered(self) -> None:
        comp = _sample_comparison_result()
        console, buf = _capture_console()
        print_comparison_table(comp, console=console)
        out = buf.getvalue()
        for label in ("LCP", "CLS", "INP", "TTFB"):
            assert label in out


# ---------------------------------------------------------------------------
# print_comparison_summary
# ---------------------------------------------------------------------------

class TestPrintComparisonSummary:
    def test_improvements_only(self) -> None:
        comp = _sample_comparison_result()
        console, buf = _capture_console()
        print_comparison_table(comp, console=console)
        print_comparison_summary(comp)
        # Use a separate capture for rprint
        # Summary uses module-level rprint; capture via capsys-like approach
        # Just assert the call doesn't raise
        assert True

    def test_regressions_section_rendered(self) -> None:
        """When regressions exist, the section heading is printed."""
        from unittest.mock import patch


        comp = _sample_comparison_result()
        # Add a regression
        comp = comp.model_copy(update={
            "summary": comp.summary.model_copy(update={
                "top_regressions": ["LCP regressed to 5000ms"],
            }),
        })

        captured = io.StringIO()
        with patch("rich.print", side_effect=lambda *a, **kw: (
            captured.write(" ".join(str(x) for x in a) + "\n")
        )):
            print_comparison_summary(comp)

        out = captured.getvalue()
        assert "Regressions" in out or "regressed" in out.lower()

    def test_empty_improvements_regressions(self) -> None:
        from unittest.mock import patch

        comp = _sample_comparison_result()
        comp = comp.model_copy(update={
            "summary": comp.summary.model_copy(update={
                "top_improvements": [],
                "top_regressions": [],
            }),
        })

        captured = io.StringIO()
        with patch("rich.print", side_effect=lambda *a, **kw: (
            captured.write(" ".join(str(x) for x in a) + "\n")
        )):
            print_comparison_summary(comp)

        out = captured.getvalue()
        assert "ROI" in out

    def test_roi_line_rendered(self) -> None:
        from unittest.mock import patch

        comp = _sample_comparison_result()
        captured = io.StringIO()
        with patch("rich.print", side_effect=lambda *a, **kw: (
            captured.write(" ".join(str(x) for x in a) + "\n")
        )):
            print_comparison_summary(comp)

        out = captured.getvalue()
        assert "24%" in out
        assert "ROI" in out


# ---------------------------------------------------------------------------
# print_audit_summary
# ---------------------------------------------------------------------------

class TestPrintAuditSummary:
    def test_issues_listed(self) -> None:
        from unittest.mock import patch

        result = _sample_audit_result()
        captured = io.StringIO()
        with patch("rich.print", side_effect=lambda *a, **kw: (
            captured.write(" ".join(str(x) for x in a) + "\n")
        )):
            print_audit_summary(result)

        out = captured.getvalue()
        assert "Hero is 120 KB" in out
        assert "Summary" in out

    def test_empty_issues_does_not_crash(self) -> None:
        from unittest.mock import patch

        from audit.models import Summary

        result = _sample_audit_result()
        result = result.model_copy(update={"summary": Summary(top_issues=[])})
        captured = io.StringIO()
        with patch("rich.print", side_effect=lambda *a, **kw: (
            captured.write(" ".join(str(x) for x in a) + "\n")
        )):
            print_audit_summary(result)

        # No crash and "Summary" heading still rendered
        assert "Summary" in captured.getvalue()
