"""
On-disk PageSpeed response cache (Sprint 7, TD-3).

Caches PageSpeed Insights API responses keyed by ``(url, strategy)`` so
repeated ``audit measure`` / ``audit compare`` calls within the TTL window
don't re-hit the network. Reduces rate-limit pain (the free tier allows
~20 requests/minute without an API key).

Cache location: ``~/.local/share/.shopify-image-audit/cache/pagespeed/<hash>.json``

Configuration:
- ``PAGESPEED_CACHE_TTL`` env var (default ``3600`` seconds = 1 hour)
- ``0`` disables caching entirely
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from engine._logging import get_logger
from engine.history import _default_history_dir

_log = get_logger()

#: Default TTL in seconds. Override with PAGESPEED_CACHE_TTL env var.
_DEFAULT_TTL = 3600


def _default_cache_dir() -> Path:
    """Return the default cache directory (sibling of the history dir)."""
    return _default_history_dir().parent / "cache" / "pagespeed"


def _env_ttl() -> int:
    """Resolve the cache TTL: PAGESPEED_CACHE_TTL env var > config > default.

    ``0`` disables caching. The config layer is ``[pagespeed] cache_ttl``
    from ``config.toml`` (Sprint 11, TD-2).
    """
    raw = os.environ.get("PAGESPEED_CACHE_TTL")
    if raw is not None:
        try:
            return max(0, int(raw))
        except ValueError:
            _log.warning("Invalid PAGESPEED_CACHE_TTL %r, using default", raw)
            return _DEFAULT_TTL
    from engine.config import get_config

    cfg_ttl = get_config().pagespeed.cache_ttl
    return cfg_ttl if cfg_ttl is not None else _DEFAULT_TTL


class ResponseCache:
    """Filesystem-backed cache for PageSpeed API responses.

    Each entry is a JSON file named by the SHA-256 hash of
    ``"url|strategy"``. The file contains ``{"timestamp": ..., "data": ...}``.

    Args:
        base_dir: Cache root directory. If ``None``, the default
            ``$XDG_DATA_HOME/.shopify-image-audit/cache/pagespeed/`` is used.
        ttl: Cache lifetime in seconds. ``0`` disables caching. If
            ``None``, the ``PAGESPEED_CACHE_TTL`` env var is consulted.
    """

    def __init__(
        self,
        base_dir: str | Path | None = None,
        *,
        ttl: int | None = None,
    ) -> None:
        self._base = Path(base_dir) if base_dir else _default_cache_dir()
        self.ttl = ttl if ttl is not None else _env_ttl()

    @property
    def base_dir(self) -> Path:
        return self._base

    def _key(self, url: str, strategy: str) -> str:
        """Return the cache filename (hash) for a (url, strategy) pair."""
        payload = f"{url}|{strategy}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _path(self, url: str, strategy: str) -> Path:
        return self._base / f"{self._key(url, strategy)}.json"

    def get(self, url: str, strategy: str) -> dict[str, Any] | None:
        """Return the cached response, or ``None`` if missing/expired/disabled."""
        if self.ttl <= 0:
            return None
        path = self._path(url, strategy)
        if not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        age = time.time() - float(entry.get("timestamp", 0))
        if age > self.ttl:
            _log.debug("Cache miss (expired): %s age=%.0fs ttl=%ds", url, age, self.ttl)
            return None
        _log.debug("Cache hit: %s age=%.0fs", url, age)
        return entry.get("data")

    def set(self, url: str, strategy: str, data: dict[str, Any]) -> None:
        """Store a response in the cache. No-op when caching is disabled."""
        if self.ttl <= 0:
            return
        path = self._path(url, strategy)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"timestamp": time.time(), "data": data}
        path.write_text(json.dumps(entry), encoding="utf-8")
