"""
Unit tests for the ML-style image ranker (``src/audit/ranker_ml.py``).

Covers:
- feature extraction (size, density, format, dimension match)
- scoring (composite, LCP penalty, clamping)
- role assignment (same vocabulary as the heuristic ranker)
- recommendation text (LCP / format / density / dim-match cases)
- the public ``rank()`` contract (preserves input keys, fills required keys,
  score in [0, 100], role in ROLES)
- differential assertions: modern > legacy, LCP < non-LCP at same payload,
  smaller > larger at same role, well-sized > oversized.
"""

from __future__ import annotations

from audit.ranker_ml import (
    ROLES,
    _f_density,
    _f_dim_match,
    _f_format,
    _f_size,
    _features,
    ml_features,
    rank,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _webp(bytes_=50_000, w=800, h=600, nw=None, nh=None, lcp=False) -> dict:
    return {
        "src": "x.webp",
        "bytes": bytes_,
        "mime": "image/webp",
        "displayed_width": w,
        "displayed_height": h,
        "natural_width": nw if nw is not None else w,
        "natural_height": nh if nh is not None else h,
        "is_lcp_candidate": lcp,
    }


def _jpeg(bytes_=200_000, w=800, h=600, lcp=False) -> dict:
    return {
        "src": "x.jpg",
        "bytes": bytes_,
        "mime": "image/jpeg",
        "displayed_width": w,
        "displayed_height": h,
        "natural_width": w,
        "natural_height": h,
        "is_lcp_candidate": lcp,
    }


# ---------------------------------------------------------------------------
# Test f_size
# ---------------------------------------------------------------------------


class TestFSize:
    def test_small_is_one(self) -> None:
        assert _f_size(10_000) == 1.0
        assert _f_size(50_000) == 1.0

    def test_huge_is_zero(self) -> None:
        assert _f_size(5_000_000) == 0.0
        assert _f_size(2_500_000) == 0.0

    def test_monotonic(self) -> None:
        prev = _f_size(50_000)
        for b in (100_000, 200_000, 500_000, 1_000_000, 2_000_000):
            cur = _f_size(b)
            assert cur <= prev, f"non-monotonic at b={b}"
            prev = cur

    def test_midpoint_in_range(self) -> None:
        s = _f_size(500_000)
        assert 0.0 < s < 1.0


# ---------------------------------------------------------------------------
# Test f_density
# ---------------------------------------------------------------------------


class TestFDensity:
    def test_dense_image_zero(self) -> None:
        # 600 KB / 600x600 area (360k px) = 1666 bpp -> 0
        assert _f_density(600_000, 360_000) == 0.0

    def test_sparse_image_one(self) -> None:
        assert _f_density(1, 100_000) > 0.99

    def test_no_area_returns_zero(self) -> None:
        # No displayed dimensions -> cannot assess density (returns 0, not 1).
        assert _f_density(50_000, 0) == 0.0

    def test_monotonic(self) -> None:
        area = 600_000
        prev = _f_density(1, area)
        for b in (10_000, 50_000, 100_000, 300_000):
            cur = _f_density(b, area)
            assert cur <= prev
            prev = cur


# ---------------------------------------------------------------------------
# Test f_format
# ---------------------------------------------------------------------------


class TestFFormat:
    def test_modern_full_score(self) -> None:
        for mime in ("image/webp", "image/avif", "image/jxl", "image/svg+xml"):
            assert _f_format(mime) == 1.0

    def test_legacy_zero(self) -> None:
        for mime in ("image/jpeg", "image/png", "image/gif"):
            assert _f_format(mime) == 0.0

    def test_empty_safe(self) -> None:
        assert _f_format("") == 0.0

    def test_substring_match(self) -> None:
        assert _f_format("image/webp;charset=utf-8") == 1.0


# ---------------------------------------------------------------------------
# Test f_dim_match
# ---------------------------------------------------------------------------


class TestFDimMatch:
    def test_perfect_match(self) -> None:
        assert (
            _f_dim_match({"displayed_width": 800, "displayed_height": 600, "natural_width": 800, "natural_height": 600})
            == 1.0
        )

    def test_close_match(self) -> None:
        # 1.5x is still "1.0"
        assert (
            _f_dim_match(
                {"displayed_width": 800, "displayed_height": 600, "natural_width": 1200, "natural_height": 900}
            )
            == 1.0
        )

    def test_severe_mismatch(self) -> None:
        # 4x or worse -> 0.0
        assert (
            _f_dim_match(
                {"displayed_width": 800, "displayed_height": 600, "natural_width": 3200, "natural_height": 2400}
            )
            == 0.0
        )

    def test_missing_dims_returns_one(self) -> None:
        assert _f_dim_match({"displayed_width": 800, "displayed_height": 600}) == 1.0

    def test_partial_penalty(self) -> None:
        s = _f_dim_match(
            {"displayed_width": 600, "displayed_height": 600, "natural_width": 1200, "natural_height": 1200}
        )
        assert 0.0 < s < 1.0


# ---------------------------------------------------------------------------
# Test _features
# ---------------------------------------------------------------------------


class TestFeatures:
    def test_returns_all_signals(self) -> None:
        f = _features(_webp())
        assert set(f.keys()) == {"f_size", "f_density", "f_format", "f_dim_match"}

    def test_values_in_unit_interval(self) -> None:
        for img in (_webp(), _jpeg(bytes_=1_200_000, lcp=True), _webp(bytes_=2_100)):
            f = _features(img)
            for v in f.values():
                assert 0.0 <= v <= 1.0

    def test_ml_features_public_alias(self) -> None:
        img = _webp()
        assert ml_features(img) == _features(img)


# ---------------------------------------------------------------------------
# Test rank()
# ---------------------------------------------------------------------------


class TestRank:
    def test_empty_list(self) -> None:
        assert rank([]) == []

    def test_required_keys_added(self) -> None:
        r = rank([_webp()])[0]
        assert "role" in r
        assert "score" in r
        assert "recommendation" in r

    def test_score_in_range(self) -> None:
        r = rank([_webp(), _jpeg(bytes_=1_500_000, lcp=True)])
        for img in r:
            assert 0 <= img["score"] <= 100

    def test_role_in_vocabulary(self) -> None:
        r = rank([_webp(), _jpeg(bytes_=50_000), _webp(bytes_=2_000)])
        for img in r:
            assert img["role"] in ROLES

    def test_preserves_original_keys(self) -> None:
        img = dict(_webp(), custom_field="preserved")
        r = rank([img])[0]
        assert r["custom_field"] == "preserved"
        assert r["src"] == "x.webp"
        assert r["bytes"] == 50_000
        assert r["mime"] == "image/webp"

    def test_does_not_mutate_input(self) -> None:
        img = _webp()
        original = dict(img)
        rank([img])
        assert img == original

    def test_order_preserved(self) -> None:
        r = rank([_webp(bytes_=50_000), _webp(bytes_=100_000), _webp(bytes_=200_000)])
        assert r[0]["bytes"] == 50_000
        assert r[1]["bytes"] == 100_000
        assert r[2]["bytes"] == 200_000

    def test_does_not_introduce_extra_keys(self) -> None:
        r = rank([_webp()])[0]
        added = set(r.keys()) - {
            "src",
            "bytes",
            "mime",
            "displayed_width",
            "displayed_height",
            "natural_width",
            "natural_height",
            "is_lcp_candidate",
        }
        assert added == {"role", "score", "recommendation"}


# ---------------------------------------------------------------------------
# Differential assertions (validate that the score RESPECTS known physics)
# ---------------------------------------------------------------------------


class TestScorePhysics:
    def test_modern_format_helps(self) -> None:
        """Same bytes + dims, WebP >= JPEG."""
        jpeg = _jpeg(bytes_=200_000)
        webp = _webp(bytes_=200_000)
        r = rank([jpeg, webp])
        assert r[1]["score"] > r[0]["score"]

    def test_lcp_penalised(self) -> None:
        """Same payload, LCP-candidate scored lower (strict LCP)."""
        non_lcp = _jpeg(bytes_=400_000)
        lcp = _jpeg(bytes_=400_000, lcp=True)
        r = rank([non_lcp, lcp])
        assert r[1]["score"] < r[0]["score"]

    def test_smaller_is_better(self) -> None:
        a = _webp(bytes_=50_000)
        b = _webp(bytes_=500_000)
        r = rank([a, b])
        assert r[0]["score"] > r[1]["score"]

    def test_svg_beats_huge_jpeg(self) -> None:
        svg = {"src": "l.svg", "bytes": 5_000, "mime": "image/svg+xml", "displayed_width": 200, "displayed_height": 60}
        jpg = _jpeg(bytes_=2_000_000, w=1200, h=600)
        r = rank([svg, jpg])
        assert r[0]["score"] > r[1]["score"] + 30

    def test_oversized_hero_penalised(self) -> None:
        bad = {
            "src": "h.jpg",
            "bytes": 1_200_000,
            "mime": "image/jpeg",
            "displayed_width": 1200,
            "displayed_height": 600,
            "natural_width": 4800,
            "natural_height": 2400,
            "is_lcp_candidate": True,
        }
        good = {
            "src": "h.jpg",
            "bytes": 95_000,
            "mime": "image/webp",
            "displayed_width": 1200,
            "displayed_height": 600,
            "natural_width": 1200,
            "natural_height": 600,
            "is_lcp_candidate": True,
        }
        r = rank([bad, good])
        # Bad must be heavily penalised; good is better but LCP-penalty caps it.
        # We don't pin an absolute threshold — we require a substantial delta
        # (>= 30 points) so the differential is meaningful and stable across
        # future scoring tweaks.
        assert r[0]["score"] < r[1]["score"]
        assert r[1]["score"] - r[0]["score"] >= 30
        # And the bad image must be in the "needs improvement" band.
        assert r[0]["score"] < 50

    def test_oversized_dim_reduces_dim_match(self) -> None:
        img = {
            "bytes": 50_000,
            "mime": "image/webp",
            "displayed_width": 600,
            "displayed_height": 600,
            "natural_width": 3000,
            "natural_height": 3000,
        }
        assert _f_dim_match(img) == 0.0


# ---------------------------------------------------------------------------
# Role assignment
# ---------------------------------------------------------------------------


class TestRoles:
    def test_large_lcp_is_hero(self) -> None:
        from audit.ranker_ml import _role_from_features

        img = _webp(bytes_=200_000, w=1200, h=600, lcp=True)
        feats = _features(img)
        assert _role_from_features(img, feats, 0) == "hero"

    def test_lcp_is_above_fold(self) -> None:
        from audit.ranker_ml import _role_from_features

        img = _webp(bytes_=50_000, w=200, h=200, lcp=True)
        feats = _features(img)
        assert _role_from_features(img, feats, 0) == "above_fold"

    def test_small_is_decorative(self) -> None:
        from audit.ranker_ml import _role_from_features

        img = _webp(bytes_=2_000, w=100, h=20)
        feats = _features(img)
        assert _role_from_features(img, feats, 0) == "decorative"

    def test_large_no_lcp_is_unknown_or_product(self) -> None:
        from audit.ranker_ml import _role_from_features

        img = _webp(bytes_=80_000, w=600, h=600)
        feats = _features(img)
        role = _role_from_features(img, feats, 0)
        assert role in ("above_fold", "product_primary", "unknown", "decorative")


# ---------------------------------------------------------------------------
# Recommendation text
# ---------------------------------------------------------------------------


class TestRecommendation:
    def test_high_score_says_ok(self) -> None:
        from audit.ranker_ml import _recommendation

        feats = {"f_size": 1.0, "f_density": 1.0, "f_format": 1.0, "f_dim_match": 1.0}
        assert _recommendation(90, False, feats, 50_000) == "OK"

    def test_lcp_heavy_image(self) -> None:
        from audit.ranker_ml import _recommendation

        feats = {"f_size": 0.0, "f_density": 0.0, "f_format": 0.0, "f_dim_match": 1.0}
        rec = _recommendation(10, True, feats, 1_200_000)
        assert "LCP" in rec

    def test_legacy_format_recommended_to_convert(self) -> None:
        from audit.ranker_ml import _recommendation

        feats = {"f_size": 0.5, "f_density": 0.5, "f_format": 0.0, "f_dim_match": 1.0}
        rec = _recommendation(40, False, feats, 100_000)
        assert "WebP" in rec or "AVIF" in rec
