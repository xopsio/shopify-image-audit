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


# ---------------------------------------------------------------------------
# network-requests fallback (Sprint 26)
# ---------------------------------------------------------------------------


def _lhr_with_network_requests(items: list[dict[str, object]]) -> dict[str, object]:
    """Build a minimal LHR whose only image source is ``network-requests``."""
    return {
        "audits": {
            "image-elements": {"details": {"items": []}},
            "resource-summary": {"details": {"items": []}},
            "network-requests": {"details": {"items": items}},
        }
    }


class TestNetworkRequestsFallback:
    """Sprint 26: when the render-tree audits are empty, fall back to
    filtering ``audits["network-requests"].details.items`` by
    ``resourceType == "Image"``."""

    def test_falls_back_to_network_requests_when_image_elements_empty(self) -> None:
        lhr = _lhr_with_network_requests(
            [
                {
                    "url": "https://cdn.example.com/hero.jpg",
                    "resourceType": "Image",
                    "transferSize": 100_000,
                    "mimeType": "image/jpeg",
                },
                {
                    "url": "https://cdn.example.com/banner.png",
                    "resourceType": "Image",
                    "transferSize": 50_000,
                    "mimeType": "image/png",
                },
            ]
        )
        images = extract_images(lhr)
        assert len(images) == 2
        urls = {img["src"] for img in images}
        assert "https://cdn.example.com/hero.jpg" in urls
        assert "https://cdn.example.com/banner.png" in urls
        # Sizes come from transferSize.
        hero = next(img for img in images if img["src"].endswith("hero.jpg"))
        assert hero["bytes"] == 100_000

    def test_prefers_image_elements_over_network_requests(self) -> None:
        """If image-elements has data, network-requests is ignored.

        The render-tree audit gives us pixel dimensions; the network
        record does not. We must never silently replace richer data
        with poorer data.
        """
        lhr = {
            "audits": {
                "image-elements": {
                    "details": {
                        "items": [
                            {
                                "url": "https://cdn.example.com/from-render.jpg",
                                "resourceSize": 1,
                                "mimeType": "image/jpeg",
                                "displayedWidth": 800,
                                "displayedHeight": 600,
                            }
                        ]
                    }
                },
                "network-requests": {
                    "details": {
                        "items": [
                            {
                                "url": "https://cdn.example.com/from-network.jpg",
                                "resourceType": "Image",
                                "transferSize": 9_999,
                            }
                        ]
                    }
                },
            }
        }
        images = extract_images(lhr)
        assert len(images) == 1
        assert images[0]["src"] == "https://cdn.example.com/from-render.jpg"
        assert images[0]["bytes"] == 1  # not the network-requests value

    def test_filters_non_image_resource_types(self) -> None:
        lhr = _lhr_with_network_requests(
            [
                {"url": "https://x/script.js", "resourceType": "Script", "transferSize": 10_000},
                {"url": "https://x/style.css", "resourceType": "Stylesheet", "transferSize": 5_000},
                {"url": "https://x/font.woff2", "resourceType": "Font", "transferSize": 20_000},
                {"url": "https://x/hero.jpg", "resourceType": "Image", "transferSize": 30_000},
                {"url": "https://x/banner.png", "resourceType": "Image", "transferSize": 40_000},
            ]
        )
        images = extract_images(lhr)
        assert len(images) == 2
        assert {img["src"] for img in images} == {
            "https://x/hero.jpg",
            "https://x/banner.png",
        }

    def test_case_insensitive_resource_type(self) -> None:
        """Lighthouse 13 emits "Image"; accept "image" too."""
        lhr = _lhr_with_network_requests(
            [
                {"url": "https://x/a.jpg", "resourceType": "Image", "transferSize": 100},
                {"url": "https://x/b.jpg", "resourceType": "image", "transferSize": 200},
                {"url": "https://x/c.jpg", "resourceType": "IMAGE", "transferSize": 300},
            ]
        )
        images = extract_images(lhr)
        assert len(images) == 3
        assert {img["bytes"] for img in images} == {100, 200, 300}

    def test_empty_when_no_image_source_at_all(self) -> None:
        """Regression: no source → no images, no crash."""
        # No audits at all
        assert extract_images({}) == []
        # image-elements absent entirely + network-requests has no images
        lhr = {
            "audits": {
                "network-requests": {
                    "details": {
                        "items": [
                            {"url": "https://x/script.js", "resourceType": "Script"},
                        ]
                    }
                }
            }
        }
        assert extract_images(lhr) == []
