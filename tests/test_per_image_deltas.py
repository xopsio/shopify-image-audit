"""
Unit tests for the per-image before/after delta table renderer.

Covers ``_render_per_image_deltas`` from ``src/audit/report.py`` and its
integration into ``_render_comparison_section``. The renderer is invoked
when ``ComparisonResult.per_image`` is non-empty; it must:
- produce a clean HTML table with one row per delta
- show different status colours (improved/regressed/unchanged/added/removed)
- handle None values gracefully (added/removed)
- return empty string when ``per_image`` is empty (so single-audit reports
  are unaffected)
"""

from __future__ import annotations

from audit.models import ComparisonResult, ImageDelta
from audit.report import _render_comparison_section, _render_per_image_deltas

# ---------------------------------------------------------------------------
# _render_per_image_deltas
# ---------------------------------------------------------------------------


class TestRenderPerImageDeltas:
    def test_empty_returns_empty_string(self) -> None:
        assert _render_per_image_deltas([]) == ""

    def test_none_returns_empty_string(self) -> None:
        # Defensive: handle None gracefully.
        assert _render_per_image_deltas(None) == ""  # type: ignore[arg-type]

    def test_single_improved_row(self) -> None:
        deltas = [
            {
                "src": "https://cdn.example.com/hero.webp",
                "role_before": "hero",
                "role_after": "hero",
                "bytes_delta": -1_000_000,
                "score_delta": 30,
                "status": "improved",
                "recommendation": "Format converted: jpeg -> webp.",
            }
        ]
        html = _render_per_image_deltas(deltas)
        assert "Per-Image Changes" in html
        assert "improved" in html
        assert "Format converted" in html
        # KB-formatted negative number
        assert "-976.6 KB" in html
        assert "+30" in html  # score delta

    def test_single_added_row(self) -> None:
        deltas = [
            {
                "src": "https://x/new.jpg",
                "bytes_delta": 50_000,
                "score_delta": None,  # No score for added images
                "status": "added",
                "recommendation": "New image; consider WebP/AVIF.",
            }
        ]
        html = _render_per_image_deltas(deltas)
        assert "added" in html
        assert "New image" in html
        # score_delta is None -> rendered as "—"
        assert "—</td>" in html

    def test_single_removed_row(self) -> None:
        deltas = [
            {
                "src": "https://x/old.jpg",
                "role_before": "hero",
                "bytes_delta": None,
                "score_delta": None,
                "status": "removed",
                "recommendation": "Image removed.",
            }
        ]
        html = _render_per_image_deltas(deltas)
        assert "removed" in html
        assert "Image removed" in html
        # role_before shows, role_after defaults to em-dash.
        assert "hero" in html
        assert "→" in html
        assert "—" in html

    def test_all_statuses_produce_status_badge(self) -> None:
        for status in ("improved", "regressed", "unchanged", "added", "removed"):
            deltas = [{"src": "x", "status": status, "bytes_delta": 0, "score_delta": 0, "recommendation": ""}]
            html = _render_per_image_deltas(deltas)
            assert status in html
            assert "status-badge" in html

    def test_long_src_is_truncated(self) -> None:
        """Source URLs longer than 50 chars are clipped to the last 50."""
        long_src = "https://" + "a" * 100 + ".com/hero.jpg"
        deltas = [{"src": long_src, "status": "unchanged", "bytes_delta": 0, "score_delta": 0, "recommendation": ""}]
        html = _render_per_image_deltas(deltas)
        # The full URL must not appear (would mean no truncation).
        assert long_src not in html
        # But the tail of the URL should still be visible.
        assert "hero.jpg" in html

    def test_xss_in_recommendation_is_escaped(self) -> None:
        """Recommendations go through html.escape — XSS payloads must be neutralised."""
        deltas = [
            {
                "src": "x.jpg",
                "status": "improved",
                "bytes_delta": 0,
                "score_delta": 0,
                "recommendation": "<script>alert('xss')</script>",
            }
        ]
        html = _render_per_image_deltas(deltas)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# _render_comparison_section integration
# ---------------------------------------------------------------------------


class TestComparisonSectionIntegration:
    def test_per_image_section_included_in_report(self) -> None:
        """When comparison has per_image data, the table must appear in the HTML."""
        comp = {
            "before": {"url": "https://before", "timestamp_utc": "2026-01-01T00:00:00Z"},
            "after": {"url": "https://after", "timestamp_utc": "2026-01-02T00:00:00Z"},
            "vitals": {
                "lcp": {"before": 4200.0, "after": 1800.0, "delta": -2400.0, "delta_pct": -57.14, "status": "improved"},
                "cls": {"before": 0.18, "after": 0.04, "delta": -0.14, "delta_pct": -77.78, "status": "improved"},
                "inp": {"before": 320.0, "after": 180.0, "delta": -140.0, "delta_pct": -43.75, "status": "improved"},
                "ttfb": {"before": 900.0, "after": 620.0, "delta": -280.0, "delta_pct": -31.11, "status": "improved"},
            },
            "images": {
                "before_count": 3,
                "after_count": 3,
                "count_delta": 0,
                "before_total_bytes": 1_625_000,
                "after_total_bytes": 139_100,
                "total_bytes_delta": -1_485_900,
                "before_total_waste": 1_570_400,
                "after_total_waste": 84_500,
                "total_waste_delta": -1_485_900,
                "before_avg_score": 10.0,
                "after_avg_score": 57.0,
                "avg_score_delta": 47.0,
            },
            "summary": {
                "top_improvements": ["LCP 4200ms -> 1800ms (-57%)"],
                "top_regressions": [],
                "roi_estimate": "Estimated ~24% conversion uplift.",
            },
            "per_image": [
                {
                    "src": "https://x/hero.jpg",
                    "role_before": "hero",
                    "role_after": "hero",
                    "bytes_delta": -1_105_000,
                    "score_delta": 40,
                    "status": "improved",
                    "recommendation": "Format converted: jpeg -> webp.",
                }
            ],
        }
        html = _render_comparison_section(comp)
        assert "Per-Image Changes" in html
        assert "Format converted" in html
        assert "improved" in html

    def test_per_image_section_omitted_when_empty(self) -> None:
        """Empty per_image -> no table, no breakage."""
        comp = {
            "before": {"url": "x", "timestamp_utc": "2026-01-01T00:00:00Z"},
            "after": {"url": "y", "timestamp_utc": "2026-01-02T00:00:00Z"},
            "vitals": {
                "lcp": {"before": 1.0, "after": 1.0, "delta": 0.0, "delta_pct": 0.0, "status": "unchanged"},
                "cls": {"before": 0.0, "after": 0.0, "delta": 0.0, "delta_pct": None, "status": "unchanged"},
                "inp": {"before": 0.0, "after": 0.0, "delta": 0.0, "delta_pct": None, "status": "unchanged"},
                "ttfb": {"before": 0.0, "after": 0.0, "delta": 0.0, "delta_pct": None, "status": "unchanged"},
            },
            "images": {
                "before_count": 0,
                "after_count": 0,
                "count_delta": 0,
                "before_total_bytes": 0,
                "after_total_bytes": 0,
                "total_bytes_delta": 0,
                "before_total_waste": 0,
                "after_total_waste": 0,
                "total_waste_delta": 0,
                "before_avg_score": 0.0,
                "after_avg_score": 0.0,
                "avg_score_delta": 0.0,
            },
            "summary": {
                "top_improvements": [],
                "top_regressions": [],
                "roi_estimate": "No significant LCP change detected.",
            },
            "per_image": [],
        }
        html = _render_comparison_section(comp)
        assert "Per-Image Changes" not in html

    def test_comparisonresult_model_input(self) -> None:
        """Accept a Pydantic ComparisonResult model, not just a dict."""
        comp = ComparisonResult.model_validate(
            {
                "before": {"url": "x", "timestamp_utc": "2026-01-01T00:00:00Z"},
                "after": {"url": "y", "timestamp_utc": "2026-01-02T00:00:00Z"},
                "vitals": {
                    "lcp": {"before": 1.0, "after": 1.0, "delta": 0.0, "delta_pct": 0.0, "status": "unchanged"},
                    "cls": {"before": 0.0, "after": 0.0, "delta": 0.0, "delta_pct": None, "status": "unchanged"},
                    "inp": {"before": 0.0, "after": 0.0, "delta": 0.0, "delta_pct": None, "status": "unchanged"},
                    "ttfb": {"before": 0.0, "after": 0.0, "delta": 0.0, "delta_pct": None, "status": "unchanged"},
                },
                "images": {
                    "before_count": 1,
                    "after_count": 1,
                    "count_delta": 0,
                    "before_total_bytes": 1000,
                    "after_total_bytes": 1000,
                    "total_bytes_delta": 0,
                    "before_total_waste": 0,
                    "after_total_waste": 0,
                    "total_waste_delta": 0,
                    "before_avg_score": 50.0,
                    "after_avg_score": 50.0,
                    "avg_score_delta": 0.0,
                },
                "summary": {
                    "top_improvements": [],
                    "top_regressions": [],
                    "roi_estimate": "no change",
                },
                "per_image": [
                    ImageDelta(
                        match_key="abc",
                        src="x.jpg",
                        before={"src": "x.jpg", "bytes": 1000, "mime": "image/jpeg", "score": 50, "role": "hero"},
                        after={"src": "x.jpg", "bytes": 1000, "mime": "image/jpeg", "score": 50, "role": "hero"},
                        bytes_delta=0,
                        score_delta=0,
                        mime_before="image/jpeg",
                        mime_after="image/jpeg",
                        status="unchanged",
                        recommendation="",
                    )
                ],
            }
        )
        html = _render_comparison_section(comp)
        assert "Per-Image Changes" in html
        assert "unchanged" in html
