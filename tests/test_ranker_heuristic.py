"""Unit tests for audit.ranker_heuristic module."""

from __future__ import annotations

import pytest

from audit.ranker_heuristic import (
    _assign_role,
    _displayed_area,
    _recommendation,
    _score_image,
    rank,
)


class TestDisplayedArea:
    """Test _displayed_area helper function."""

    def test_both_dimensions_present(self):
        img = {"displayed_width": 800, "displayed_height": 600}
        assert _displayed_area(img) == 480_000

    def test_fallback_to_natural(self):
        img = {"natural_width": 1200, "natural_height": 800}
        assert _displayed_area(img) == 960_000

    def test_missing_dimensions(self):
        img = {"bytes": 50000}
        assert _displayed_area(img) == 0

    def test_zero_dimensions(self):
        img = {"displayed_width": 0, "displayed_height": 600}
        assert _displayed_area(img) == 0

    def test_partial_dimensions(self):
        img = {"displayed_width": 800}
        assert _displayed_area(img) == 0


class TestAssignRole:
    """Test _assign_role heuristic."""

    def test_hero_lcp_large_area(self):
        img = {"is_lcp_candidate": True, "displayed_width": 1200, "displayed_height": 600}
        role = _assign_role(img, 0)
        assert role == "hero"

    def test_above_fold_lcp_small_area(self):
        img = {"is_lcp_candidate": True, "displayed_width": 400, "displayed_height": 300}
        role = _assign_role(img, 0)
        assert role == "above_fold"

    def test_above_fold_first_image_large(self):
        img = {
            "is_lcp_candidate": False,
            "displayed_width": 600,
            "displayed_height": 300,
        }
        role = _assign_role(img, 0)
        assert role == "above_fold"

    def test_product_primary_large_and_heavy_early_index(self):
        img = {
            "displayed_width": 500,
            "displayed_height": 500,
            "bytes": 100_000,
        }
        role = _assign_role(img, 1)
        assert role == "product_primary"

    def test_product_secondary_large_and_heavy_late_index(self):
        img = {
            "displayed_width": 500,
            "displayed_height": 500,
            "bytes": 100_000,
        }
        role = _assign_role(img, 5)
        assert role == "product_secondary"

    def test_decorative_small_area(self):
        img = {"displayed_width": 100, "displayed_height": 100, "bytes": 3000}
        role = _assign_role(img, 2)
        assert role == "decorative"

    def test_decorative_small_bytes(self):
        img = {"displayed_width": 200, "displayed_height": 200, "bytes": 4000}
        role = _assign_role(img, 3)
        assert role == "decorative"

    def test_unknown_fallback(self):
        img = {"displayed_width": 300, "displayed_height": 200, "bytes": 30_000}
        role = _assign_role(img, 4)
        assert role == "unknown"


class TestScoreImage:
    """Test _score_image scoring heuristic."""

    def test_excellent_score_low_bpp(self):
        img = {"displayed_width": 1000, "displayed_height": 1000, "bytes": 30_000}
        score = _score_image(img, "hero")
        assert score == 95

    def test_good_score_moderate_bpp(self):
        img = {"displayed_width": 1000, "displayed_height": 1000, "bytes": 60_000}
        score = _score_image(img, "hero")
        assert score == 85

    def test_medium_score_higher_bpp(self):
        img = {"displayed_width": 1000, "displayed_height": 1000, "bytes": 120_000}
        score = _score_image(img, "hero")
        assert score == 70

    def test_low_score_very_high_bpp(self):
        img = {"displayed_width": 1000, "displayed_height": 1000, "bytes": 300_000}
        score = _score_image(img, "hero")
        assert score <= 40

    def test_lcp_penalty_very_heavy(self):
        img = {
            "displayed_width": 1200,
            "displayed_height": 800,
            "bytes": 600_000,
            "is_lcp_candidate": True,
        }
        score = _score_image(img, "hero")
        # Base score would be low due to high bpp, penalty makes it even lower
        assert score < 50

    def test_lcp_penalty_heavy(self):
        img = {
            "displayed_width": 1200,
            "displayed_height": 800,
            "bytes": 250_000,
            "is_lcp_candidate": True,
        }
        score_with_lcp = _score_image(img, "hero")
        # Without LCP flag
        img_no_lcp = img.copy()
        img_no_lcp["is_lcp_candidate"] = False
        score_without_lcp = _score_image(img_no_lcp, "hero")
        assert score_with_lcp < score_without_lcp

    def test_score_bounds_never_exceed_100(self):
        img = {"displayed_width": 2000, "displayed_height": 2000, "bytes": 10_000}
        score = _score_image(img, "hero")
        assert 0 <= score <= 100

    def test_score_bounds_never_below_0(self):
        img = {"displayed_width": 100, "displayed_height": 100, "bytes": 500_000}
        score = _score_image(img, "hero")
        assert 0 <= score <= 100

    def test_zero_area_handles_gracefully(self):
        img = {"bytes": 100_000}
        score = _score_image(img, "unknown")
        assert isinstance(score, int)
        assert 0 <= score <= 100


class TestRecommendation:
    """Test _recommendation text generation."""

    def test_optimize_lcp_heavy(self):
        img = {"bytes": 500_000, "is_lcp_candidate": True}
        rec = _recommendation(img, "hero", 50)
        assert "LCP" in rec
        assert "compress" in rec.lower() or "modern format" in rec.lower()

    def test_improve_lcp_low_score(self):
        img = {"bytes": 200_000, "is_lcp_candidate": True}
        rec = _recommendation(img, "above_fold", 60)
        assert "LCP" in rec

    def test_optimize_hero_low_score(self):
        img = {"bytes": 150_000, "is_lcp_candidate": False}
        rec = _recommendation(img, "hero", 70)
        assert "hero" in rec.lower() or "optimize" in rec.lower()

    def test_reduce_above_fold_heavy(self):
        img = {"bytes": 250_000, "is_lcp_candidate": False}
        rec = _recommendation(img, "above_fold", 75)
        assert "above" in rec.lower() or "fold" in rec.lower()

    def test_product_images_responsive(self):
        img = {"bytes": 180_000, "is_lcp_candidate": False}
        rec = _recommendation(img, "product_primary", 65)
        assert "responsive" in rec.lower() or "lazy" in rec.lower()

    def test_decorative_lazy_load(self):
        img = {"bytes": 60_000, "is_lcp_candidate": False}
        rec = _recommendation(img, "decorative", 70)
        assert "lazy" in rec.lower() or "decorative" in rec.lower()

    def test_ok_high_score(self):
        img = {"bytes": 30_000, "is_lcp_candidate": False}
        rec = _recommendation(img, "hero", 95)
        assert rec == "OK"

    def test_generic_fallback(self):
        img = {"bytes": 100_000, "is_lcp_candidate": False}
        rec = _recommendation(img, "unknown", 75)
        assert "review" in rec.lower() or "performance" in rec.lower()


class TestRank:
    """Test the main rank() function."""

    def test_empty_list(self):
        result = rank([])
        assert result == []

    def test_single_image(self):
        images = [
            {
                "src": "test.jpg",
                "bytes": 50_000,
                "mime": "image/jpeg",
                "displayed_width": 800,
                "displayed_height": 600,
                "is_lcp_candidate": True,
            }
        ]
        result = rank(images)
        assert len(result) == 1
        assert "role" in result[0]
        assert "score" in result[0]
        assert "recommendation" in result[0]
        assert result[0]["role"] in [
            "hero",
            "above_fold",
            "product_primary",
            "product_secondary",
            "decorative",
            "unknown",
        ]
        assert 0 <= result[0]["score"] <= 100

    def test_multiple_images_preserve_order(self):
        images = [
            {"src": f"image{i}.jpg", "bytes": 50_000, "mime": "image/jpeg"}
            for i in range(5)
        ]
        result = rank(images)
        assert len(result) == 5
        for i, img in enumerate(result):
            assert img["src"] == f"image{i}.jpg"

    def test_adds_required_fields(self):
        images = [
            {
                "src": "test.jpg",
                "bytes": 100_000,
                "mime": "image/jpeg",
                "displayed_width": 1000,
                "displayed_height": 1000,
            }
        ]
        result = rank(images)
        assert "role" in result[0]
        assert "score" in result[0]
        assert "recommendation" in result[0]

    def test_preserves_original_fields(self):
        images = [
            {
                "src": "test.jpg",
                "bytes": 100_000,
                "mime": "image/jpeg",
                "displayed_width": 800,
                "displayed_height": 600,
                "natural_width": 1600,
                "natural_height": 1200,
                "custom_field": "preserved",
            }
        ]
        result = rank(images)
        assert result[0]["src"] == "test.jpg"
        assert result[0]["bytes"] == 100_000
        assert result[0]["mime"] == "image/jpeg"
        assert result[0]["custom_field"] == "preserved"

    def test_realistic_shopify_scenario(self):
        """Test with a realistic Shopify page scenario."""
        images = [
            {  # Hero LCP
                "src": "hero.jpg",
                "bytes": 400_000,
                "mime": "image/jpeg",
                "displayed_width": 1200,
                "displayed_height": 600,
                "is_lcp_candidate": True,
            },
            {  # Product image
                "src": "product1.jpg",
                "bytes": 150_000,
                "mime": "image/jpeg",
                "displayed_width": 600,
                "displayed_height": 600,
            },
            {  # Another product
                "src": "product2.jpg",
                "bytes": 150_000,
                "mime": "image/jpeg",
                "displayed_width": 600,
                "displayed_height": 600,
            },
            {  # Logo
                "src": "logo.png",
                "bytes": 5_000,
                "mime": "image/png",
                "displayed_width": 200,
                "displayed_height": 60,
            },
        ]
        result = rank(images)

        assert len(result) == 4
        assert result[0]["role"] == "hero"
        assert result[1]["role"] in ["product_primary", "above_fold"]
        assert result[3]["role"] == "decorative"

        # All images should have valid scores
        for img in result:
            assert 0 <= img["score"] <= 100
            assert img["recommendation"]

