"""
Unit tests for ``src/core/`` modules (image_extractor + performance_scorer).

These tests consume the previously-orphaned fixtures under ``tests/fixtures/``
(extract_input.json, expected_images.json, expected_scores.json), which were
authored against the core modules but had no test wiring them up.

Note: ``core/performance_scorer`` uses a *different* scoring formula than the
pipeline's ``audit/ranker_heuristic`` (absolute-bytes + modern-format bonus +
LCP penalty, vs. area-based bpp). Both are intentionally retained side by side
(see governance v1.2); these tests pin the core scorer's behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.image_extractor import extract_images
from core.performance_scorer import calculate_score

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures"

EXTRACT_INPUT = FIXTURES / "extract_input.json"
EXPECTED_IMAGES = FIXTURES / "expected_images.json"
EXPECTED_SCORES = FIXTURES / "expected_scores.json"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def lhr_data() -> dict[str, Any]:
    with open(EXTRACT_INPUT, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected_images() -> list[dict[str, Any]]:
    with open(EXPECTED_IMAGES, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def expected_scores() -> list[dict[str, Any]]:
    with open(EXPECTED_SCORES, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# image_extractor
# ---------------------------------------------------------------------------

class TestExtractImages:
    def test_returns_normalized_list(self, lhr_data: dict[str, Any]) -> None:
        images = extract_images(lhr_data)
        assert isinstance(images, list)
        assert len(images) == 2

    def test_required_keys_present(self, lhr_data: dict[str, Any]) -> None:
        for img in extract_images(lhr_data):
            for key in ("src", "bytes", "mime", "is_lcp_candidate"):
                assert key in img, f"missing key {key}"

    def test_matches_expected_images(self, lhr_data, expected_images) -> None:
        """extract_images output must match expected_images.json exactly."""
        images = extract_images(lhr_data)
        assert images == expected_images

    def test_lcp_candidate_marked(self, lhr_data: dict[str, Any]) -> None:
        images = extract_images(lhr_data)
        lcp = [i for i in images if i.get("is_lcp_candidate")]
        assert len(lcp) == 1
        assert lcp[0]["src"] == "https://cdn.example.com/hero.webp"

    def test_non_dict_input_returns_empty(self) -> None:
        assert extract_images([]) == []  # type: ignore[arg-type]
        assert extract_images("not a dict") == []  # type: ignore[arg-type]
        assert extract_images(None) == []  # type: ignore[arg-type]

    def test_missing_audits_returns_empty(self) -> None:
        assert extract_images({"foo": "bar"}) == []

    def test_dedupes_by_url(self) -> None:
        """The same URL appearing twice should only be emitted once."""
        lhr = {
            "audits": {
                "image-elements": {
                    "details": {
                        "items": [
                            {"url": "https://x.com/a.png", "resourceSize": 1000},
                            {"url": "https://x.com/a.png", "resourceSize": 2000},
                        ]
                    }
                }
            }
        }
        images = extract_images(lhr)
        assert len(images) == 1
        assert images[0]["bytes"] == 1000  # first occurrence wins


# ---------------------------------------------------------------------------
# performance_scorer
# ---------------------------------------------------------------------------

class TestCalculateScore:
    def test_scores_match_expected(self, expected_images, expected_scores) -> None:
        """calculate_score must reproduce expected_scores.json for the fixtures."""
        by_src = {row["src"]: row["score"] for row in expected_scores}
        for img in expected_images:
            assert calculate_score(img) == by_src[img["src"]]

    def test_hero_is_heavy_lcp(self) -> None:
        # 320 KB WebP LCP image -> 50 base - 15 LCP + 5 modern = 40
        score = calculate_score(
            {"bytes": 320_000, "mime": "image/webp", "is_lcp_candidate": True}
        )
        assert score == 40

    def test_small_image_scores_high(self) -> None:
        score = calculate_score({"bytes": 24_000, "mime": "image/png"})
        assert score == 95

    def test_score_range(self) -> None:
        for b in (0, 1, 50_000, 150_000, 300_000, 600_000, 1_000_000):
            score = calculate_score({"bytes": b, "mime": "image/jpeg"})
            assert 0 <= score <= 100

    def test_modern_format_bonus(self) -> None:
        base = calculate_score({"bytes": 100_000, "mime": "image/jpeg"})
        modern = calculate_score({"bytes": 100_000, "mime": "image/webp"})
        assert modern == base + 5

    def test_lcp_penalty_applied(self) -> None:
        non_lcp = calculate_score({"bytes": 400_000, "mime": "image/jpeg"})
        lcp = calculate_score(
            {"bytes": 400_000, "mime": "image/jpeg", "is_lcp_candidate": True}
        )
        assert lcp < non_lcp

    def test_non_dict_returns_zero(self) -> None:
        assert calculate_score(None) == 0  # type: ignore[arg-type]
        assert calculate_score("string") == 0  # type: ignore[arg-type]

    def test_clamped_to_zero(self) -> None:
        # Huge LCP image would go negative without clamping.
        score = calculate_score(
            {"bytes": 5_000_000, "mime": "image/jpeg", "is_lcp_candidate": True}
        )
        assert score == 0

    def test_invalid_bytes_treated_as_zero(self) -> None:
        score = calculate_score({"bytes": "not-a-number", "mime": "image/jpeg"})
        assert score == 95  # treated as 0 bytes
