"""
Snapshot tests for deterministic HTML render functions (Sprint 5, TD-1).

Locks down every byte-stable render function in ``src/audit/report.py`` and
``src/engine/history.py``. These golden files catch silent CSS / layout
regressions on every PR — substring assertions can't detect "the colour
changed but the class is still there".

How to regenerate after an intentional change::

    pytest tests/test_snapshots.py --snapshot-update

How to inspect what changed::

    diff tests/__snapshots__/test_snapshots.ambr  # in your editor
"""

from __future__ import annotations

import pytest

from audit.report import (
    _aggregate_stats,
    _render_comparison_section,
    _render_footer,
    _render_head,
    _render_image_table,
    _render_per_image_deltas,
    _render_role_distribution,
    _render_stats,
    _render_vitals,
)
from engine.history import HistoryEntry, generate_trend_html

# All render functions produce HTML strings — we use the default
# ``syrupy.TextSnapshotFixture`` which serialises strings byte-stable.


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _minimal_audit_payload() -> dict:
    """A small but complete AuditResult payload for rendering."""
    return {
        "meta": {
            "url": "https://demo.myshopify.com",
            "timestamp_utc": "2026-07-30T15:00:00Z",
            "device": "mobile",
            "runs": 3,
            "tool": "lighthouse",
        },
        "vitals": {
            "lcp_ms": 2200.0,
            "cls": 0.08,
            "inp_ms": 180.0,
            "ttfb_ms": 700.0,
        },
        "images": [
            {
                "src": "https://cdn.example.com/hero.jpg",
                "role": "hero",
                "score": 75,
                "bytes": 120_000,
                "mime": "image/jpeg",
                "displayed_width": 1200,
                "displayed_height": 600,
                "natural_width": 2400,
                "natural_height": 1200,
                "is_lcp_candidate": True,
                "waste_bytes_est": 30000,
                "recommendation": "Convert to WebP.",
            },
            {
                "src": "https://cdn.example.com/thumb.png",
                "role": "decorative",
                "score": 95,
                "bytes": 45_000,
                "mime": "image/png",
                "displayed_width": 200,
                "displayed_height": 60,
            },
            {
                "src": "https://cdn.example.com/product.jpg",
                "role": "product_primary",
                "score": 60,
                "bytes": 380_000,
                "mime": "image/jpeg",
                "displayed_width": 600,
                "displayed_height": 600,
            },
        ],
        "summary": {
            "top_issues": [
                "Hero image is 1.2 MB — consider WebP/AVIF.",
                "Product images exceed display dimensions.",
            ],
        },
    }


@pytest.fixture
def audit_payload() -> dict:
    return _minimal_audit_payload()


@pytest.fixture
def audit_payload_with_comparison(audit_payload: dict) -> tuple[dict, dict]:
    """Audit payload paired with a comparison dict for section rendering."""
    comparison = {
        "before": {
            "url": "https://demo.myshopify.com",
            "timestamp_utc": "2026-07-23T10:00:00Z",
        },
        "after": audit_payload["meta"],
        "vitals": {
            "lcp": {"before": 4200.0, "after": 2200.0, "delta": -2000.0, "delta_pct": -47.6, "status": "improved"},
            "cls": {"before": 0.18, "after": 0.08, "delta": -0.10, "delta_pct": -55.6, "status": "improved"},
            "inp": {"before": 320.0, "after": 180.0, "delta": -140.0, "delta_pct": -43.8, "status": "improved"},
            "ttfb": {"before": 900.0, "after": 700.0, "delta": -200.0, "delta_pct": -22.2, "status": "improved"},
        },
        "images": {
            "before_count": 3,
            "after_count": 3,
            "count_delta": 0,
            "before_total_bytes": 545000,
            "after_total_bytes": 545000,
            "total_bytes_delta": 0,
            "before_total_waste": 30000,
            "after_total_waste": 30000,
            "total_waste_delta": 0,
            "before_avg_score": 76.7,
            "after_avg_score": 76.7,
            "avg_score_delta": 0.0,
        },
        "summary": {
            "top_improvements": ["LCP 4200ms → 2200ms (-48%)"],
            "top_regressions": [],
            "roi_estimate": "Estimated ~20% conversion uplift from a 2000ms LCP improvement.",
            "recommendations": [],
        },
        "per_image": [
            {
                "match_key": "abc123",
                "src": "https://cdn.example.com/hero.jpg",
                "role_before": "hero",
                "role_after": "hero",
                "before": {"src": "https://cdn.example.com/hero.jpg", "bytes": 1200000, "mime": "image/jpeg"},
                "after": {"src": "https://cdn.example.com/hero.jpg", "bytes": 120000, "mime": "image/jpeg"},
                "bytes_delta": -1080000,
                "score_delta": 0,
                "mime_before": "image/jpeg",
                "mime_after": "image/jpeg",
                "status": "improved",
                "recommendation": "Image shrunk significantly.",
            },
            {
                "match_key": "def456",
                "src": "https://cdn.example.com/thumb.png",
                "role_before": "decorative",
                "role_after": "decorative",
                "before": {"src": "https://cdn.example.com/thumb.png", "bytes": 45000, "mime": "image/png"},
                "after": {"src": "https://cdn.example.com/thumb.png", "bytes": 45000, "mime": "image/png"},
                "bytes_delta": 0,
                "score_delta": 0,
                "mime_before": "image/png",
                "mime_after": "image/png",
                "status": "unchanged",
                "recommendation": "",
            },
            {
                "match_key": "ghi789",
                "src": "https://cdn.example.com/product.jpg",
                "role_before": "product_primary",
                "role_after": None,
                "before": {"src": "https://cdn.example.com/product.jpg", "bytes": 380000, "mime": "image/jpeg"},
                "after": None,
                "bytes_delta": -380000,
                "score_delta": None,
                "mime_before": "image/jpeg",
                "mime_after": None,
                "status": "removed",
                "recommendation": "Image removed.",
            },
            {
                "match_key": "jkl012",
                "src": "https://cdn.example.com/new-thumb.webp",
                "role_before": None,
                "role_after": "decorative",
                "before": None,
                "after": {"src": "https://cdn.example.com/new-thumb.webp", "bytes": 30000, "mime": "image/webp"},
                "bytes_delta": 30000,
                "score_delta": None,
                "mime_before": None,
                "mime_after": "image/webp",
                "status": "added",
                "recommendation": "New image; consider WebP/AVIF.",
            },
            {
                "match_key": "mno345",
                "src": "https://cdn.example.com/regressed.jpg",
                "role_before": "decorative",
                "role_after": "decorative",
                "before": {"src": "https://cdn.example.com/regressed.jpg", "bytes": 50000, "mime": "image/jpeg"},
                "after": {"src": "https://cdn.example.com/regressed.jpg", "bytes": 100000, "mime": "image/jpeg"},
                "bytes_delta": 50000,
                "score_delta": -10,
                "mime_before": "image/jpeg",
                "mime_after": "image/jpeg",
                "status": "regressed",
                "recommendation": "Image grew; review.",
            },
        ],
    }
    return audit_payload, comparison


# ---------------------------------------------------------------------------
# _render_head — 4 brand permutations
# ---------------------------------------------------------------------------


class TestRenderHeadSnapshot:
    def test_default_no_brand(self, snapshot) -> None:
        out = _render_head()
        assert out == snapshot

    def test_brand_color_only(self, snapshot) -> None:
        out = _render_head(brand_color="#3498db")
        assert out == snapshot

    def test_brand_logo_only(self, snapshot) -> None:
        out = _render_head(brand_logo=("image/png", "iVBORw0KGgo="))
        assert out == snapshot

    def test_brand_color_and_logo(self, snapshot) -> None:
        out = _render_head(
            brand_logo=("image/png", "iVBORw0KGgo="),
            brand_color="#ff6b35",
        )
        assert out == snapshot


# ---------------------------------------------------------------------------
# _render_vitals — all 4 cards in one render
# ---------------------------------------------------------------------------


class TestRenderVitalsSnapshot:
    def test_all_vitals(self, snapshot, audit_payload: dict) -> None:
        out = _render_vitals(audit_payload["vitals"])
        assert out == snapshot


# ---------------------------------------------------------------------------
# _render_stats — currently has zero direct tests
# ---------------------------------------------------------------------------


class TestRenderStatsSnapshot:
    def test_aggregate_stats_basic(self, snapshot, audit_payload: dict) -> None:
        out = _render_stats(_aggregate_stats(audit_payload["images"]))
        assert out == snapshot


# ---------------------------------------------------------------------------
# _render_image_table — currently has zero direct tests
# ---------------------------------------------------------------------------


class TestRenderImageTableSnapshot:
    def test_table_with_three_images(self, snapshot, audit_payload: dict) -> None:
        out = _render_image_table(audit_payload["images"])
        assert out == snapshot


# ---------------------------------------------------------------------------
# _render_role_distribution
# ---------------------------------------------------------------------------


class TestRenderRoleDistributionSnapshot:
    def test_single_role(self, snapshot) -> None:
        out = _render_role_distribution({"hero": 1})
        assert out == snapshot

    def test_multiple_roles_sorted(self, snapshot) -> None:
        out = _render_role_distribution(
            {
                "hero": 1,
                "above_fold": 3,
                "product_primary": 5,
                "decorative": 2,
                "unknown": 1,
            }
        )
        assert out == snapshot


# ---------------------------------------------------------------------------
# _render_comparison_section
# ---------------------------------------------------------------------------


class TestRenderComparisonSectionSnapshot:
    def test_no_comparison(self, snapshot) -> None:
        out = _render_comparison_section(None)
        assert out == snapshot

    def test_with_comparison_data(self, snapshot, audit_payload_with_comparison: tuple[dict, dict]) -> None:
        _payload, comparison = audit_payload_with_comparison
        out = _render_comparison_section(comparison)
        assert out == snapshot


# ---------------------------------------------------------------------------
# _render_per_image_deltas — 5 status colours + empty
# ---------------------------------------------------------------------------


class TestRenderPerImageDeltasSnapshot:
    def test_empty(self, snapshot) -> None:
        out = _render_per_image_deltas([])
        assert out == snapshot

    def test_improved(self, snapshot) -> None:
        out = _render_per_image_deltas(
            [
                {
                    "match_key": "a",
                    "src": "https://cdn.example.com/hero.jpg",
                    "role_before": "hero",
                    "role_after": "hero",
                    "before": {},
                    "after": {},
                    "bytes_delta": -50000,
                    "score_delta": 10,
                    "mime_before": "image/jpeg",
                    "mime_after": "image/jpeg",
                    "status": "improved",
                    "recommendation": "Great.",
                }
            ]
        )
        assert out == snapshot

    def test_regressed(self, snapshot) -> None:
        out = _render_per_image_deltas(
            [
                {
                    "match_key": "a",
                    "src": "https://cdn.example.com/hero.jpg",
                    "role_before": "hero",
                    "role_after": "hero",
                    "before": {},
                    "after": {},
                    "bytes_delta": 50000,
                    "score_delta": -10,
                    "mime_before": "image/jpeg",
                    "mime_after": "image/jpeg",
                    "status": "regressed",
                    "recommendation": "Bad.",
                }
            ]
        )
        assert out == snapshot

    def test_added(self, snapshot) -> None:
        out = _render_per_image_deltas(
            [
                {
                    "match_key": "a",
                    "src": "https://cdn.example.com/new.jpg",
                    "role_before": None,
                    "role_after": "decorative",
                    "before": None,
                    "after": {},
                    "bytes_delta": 30000,
                    "score_delta": None,
                    "mime_before": None,
                    "mime_after": "image/webp",
                    "status": "added",
                    "recommendation": "New.",
                }
            ]
        )
        assert out == snapshot

    def test_removed(self, snapshot) -> None:
        out = _render_per_image_deltas(
            [
                {
                    "match_key": "a",
                    "src": "https://cdn.example.com/old.jpg",
                    "role_before": "decorative",
                    "role_after": None,
                    "before": {},
                    "after": None,
                    "bytes_delta": -30000,
                    "score_delta": None,
                    "mime_before": "image/jpeg",
                    "mime_after": None,
                    "status": "removed",
                    "recommendation": "Gone.",
                }
            ]
        )
        assert out == snapshot

    def test_unchanged(self, snapshot) -> None:
        out = _render_per_image_deltas(
            [
                {
                    "match_key": "a",
                    "src": "https://cdn.example.com/unchanged.jpg",
                    "role_before": "decorative",
                    "role_after": "decorative",
                    "before": {},
                    "after": {},
                    "bytes_delta": 0,
                    "score_delta": 0,
                    "mime_before": "image/jpeg",
                    "mime_after": "image/jpeg",
                    "status": "unchanged",
                    "recommendation": "",
                }
            ]
        )
        assert out == snapshot


# ---------------------------------------------------------------------------
# _render_footer
# ---------------------------------------------------------------------------


class TestRenderFooterSnapshot:
    def test_footer_with_source_file(self, snapshot) -> None:
        payload = _minimal_audit_payload()
        payload["_source_file"] = "/tmp/my_audit.json"
        out = _render_footer(payload)
        assert out == snapshot


# ---------------------------------------------------------------------------
# generate_trend_html — empty / single / multi
# ---------------------------------------------------------------------------


def _entry(timestamp: str, lcp: float, cls: float, inp: float, ttfb: float, **kwargs) -> HistoryEntry:
    """Build a HistoryEntry with deterministic content."""
    base = {
        "hostname": "mystore.myshopify.com",
        "timestamp_utc": timestamp,
        "url": "https://mystore.myshopify.com",
        "device": "mobile",
        "path": f"mystore.myshopify.com/{timestamp.replace(':', '-')}.json",
        "lcp_ms": lcp,
        "cls": cls,
        "inp_ms": inp,
        "ttfb_ms": ttfb,
        "image_count": 3,
        "total_bytes": 545000,
        "avg_score": 76.7,
    }
    base.update(kwargs)
    return HistoryEntry(**base)


class TestGenerateTrendHtmlSnapshot:
    def test_empty(self, snapshot) -> None:
        out = generate_trend_html("mystore.myshopify.com", [])
        assert out == snapshot

    def test_single_entry_good_vitals(self, snapshot) -> None:
        entry = _entry("2026-07-30T15:00:00Z", 1800.0, 0.05, 100.0, 400.0)
        out = generate_trend_html("mystore.myshopify.com", [entry])
        assert out == snapshot

    def test_multi_entry_mixed_vitals(self, snapshot) -> None:
        entries = [
            _entry("2026-07-23T10:00:00Z", 4200.0, 0.18, 320.0, 900.0, label="Baseline"),
            _entry("2026-07-30T15:00:00Z", 1800.0, 0.05, 100.0, 400.0, label="After optimisation"),
        ]
        out = generate_trend_html("mystore.myshopify.com", entries)
        assert out == snapshot

    def test_multi_entry_poor_vitals(self, snapshot) -> None:
        entries = [
            _entry("2026-07-23T10:00:00Z", 5000.0, 0.30, 600.0, 2000.0, label="Critical state"),
            _entry("2026-07-30T15:00:00Z", 3500.0, 0.20, 400.0, 1500.0, label="After partial fix"),
        ]
        out = generate_trend_html("mystore.myshopify.com", entries)
        assert out == snapshot
