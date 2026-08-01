"""
Unit tests for ``src/core/image_extractor.py``.

Consumes the fixtures under ``tests/fixtures/`` (extract_input.json,
expected_images.json) which were authored against the core module but had
no test wiring them up. (Previously also tested ``core.performance_scorer``,
but that module was removed in the Sprint 3 refactor plan: it had no
production callers, and the rankers in ``audit/`` are the real scoring path.)
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.image_extractor import extract_images
from tests import FIXTURES

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
