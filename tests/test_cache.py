"""
Tests for ``src/integrations/_cache.py`` (Sprint 7, TD-3) — on-disk
PageSpeed response cache.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from integrations._cache import ResponseCache


class TestResponseCacheBasic:
    def test_miss_returns_none(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path, ttl=60)
        assert cache.get("https://x", "mobile") is None

    def test_set_then_get(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path, ttl=60)
        cache.set("https://x", "mobile", {"lcp": 1800})
        result = cache.get("https://x", "mobile")
        assert result == {"lcp": 1800}

    def test_different_strategies_dont_collide(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path, ttl=60)
        cache.set("https://x", "mobile", {"a": 1})
        cache.set("https://x", "desktop", {"b": 2})
        assert cache.get("https://x", "mobile") == {"a": 1}
        assert cache.get("https://x", "desktop") == {"b": 2}

    def test_different_urls_dont_collide(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path, ttl=60)
        cache.set("https://a", "mobile", {"a": 1})
        cache.set("https://b", "mobile", {"b": 2})
        assert cache.get("https://a", "mobile") == {"a": 1}
        assert cache.get("https://b", "mobile") == {"b": 2}


class TestResponseCacheTTL:
    def test_expired_entry_returns_none(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path, ttl=60)
        cache.set("https://x", "mobile", {"data": 1})
        # Manually backdate the timestamp to simulate expiry.
        path = cache._path("https://x", "mobile")  # noqa: SLF001
        entry = json.loads(path.read_text())
        entry["timestamp"] = time.time() - 120  # 2 minutes ago
        path.write_text(json.dumps(entry))
        assert cache.get("https://x", "mobile") is None

    def test_ttl_zero_disables_caching(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path, ttl=0)
        cache.set("https://x", "mobile", {"data": 1})
        # set() is a no-op when ttl=0; get() always returns None.
        assert cache.get("https://x", "mobile") is None
        # No file should have been written.
        assert not list(tmp_path.glob("*.json"))


class TestResponseCacheEnvVar:
    def test_env_ttl_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PAGESPEED_CACHE_TTL", raising=False)
        cache = ResponseCache("/tmp/unused")
        assert cache.ttl == 3600

    def test_env_ttl_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("PAGESPEED_CACHE_TTL", "120")
        cache = ResponseCache(tmp_path)
        assert cache.ttl == 120

    def test_env_ttl_zero_disables(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("PAGESPEED_CACHE_TTL", "0")
        cache = ResponseCache(tmp_path)
        assert cache.ttl == 0

    def test_env_ttl_invalid_falls_back(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("PAGESPEED_CACHE_TTL", "not-a-number")
        cache = ResponseCache("/tmp/unused")
        assert cache.ttl == 3600


class TestResponseCacheCorrupt:
    def test_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        cache = ResponseCache(tmp_path, ttl=60)
        path = cache._path("https://x", "mobile")  # noqa: SLF001
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        assert cache.get("https://x", "mobile") is None


class TestPageSpeedClientCacheIntegration:
    """Verify PageSpeedAPIClient consults the cache."""

    def test_cache_hit_avoids_network(
        self, tmp_path: Path,
    ) -> None:
        import responses

        from integrations._cache import ResponseCache
        from integrations.pagespeed_api import PageSpeedAPIClient

        cache = ResponseCache(tmp_path, ttl=3600)
        client = PageSpeedAPIClient(cache=cache, retry_delay=0.0)

        mock_response = {
            "lighthouseResult": {
                "audits": {
                    "largest-contentful-paint": {"numericValue": 1800},
                    "cumulative-layout-shift": {"numericValue": 0.05},
                    "experimental-interaction-to-next-patch": {"numericValue": 120},
                    "server-response-time": {"numericValue": 400},
                },
                "categories": {"performance": {"score": 0.95}},
                "configSettings": {"formFactor": "mobile"},
                "finalUrl": "https://demo.myshopify.com",
                "fetchTime": "2026-07-31T09:00:00Z",
            }
        }

        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            rsps.add(
                responses.GET,
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                json=mock_response,
                status=200,
            )
            # First call hits the network.
            metrics1 = client.get_metrics("https://demo.myshopify.com")
            assert metrics1.lcp == 1.8

        # Second call should hit the cache — no responses mock needed.
        metrics2 = client.get_metrics("https://demo.myshopify.com")
        assert metrics2.lcp == 1.8
