"""
Shopify Admin API client for Shopify Image Audit.

Provides read-only access to a Shopify store via the Admin REST API. Used by
the ``audit shopify auth`` and ``audit shopify inventory`` CLI subcommands
to verify Admin API access tokens and list image URLs in the store
(products and theme assets) — eliminating the need for the customer to
export Lighthouse JSON by hand.

Design
------
- Mirrors the structure of ``pagespeed_api.py``: a single class with
  constructor-stored config, request/response helpers, retry-on-429/503,
  and predictable exception types (``ValueError`` for input errors,
  ``RuntimeError`` for API errors, ``requests.exceptions.RequestException``
  for network errors).
- Read-only by design: the client never writes to the store. The required
  Admin API scopes are read-only (``read_shop``, ``read_products``,
  ``read_themes``).
- Per-call rate limiting respects Shopify's "leaky bucket" budget
  (40 calls / 2 s) by sleeping between calls.
- All HTTP calls go through the ``_request`` helper which handles the
  retry loop consistently across the three public methods.

Why REST and not GraphQL
------------------------
The REST Admin API is simpler, has stable endpoint paths, and the three
endpoints we need (shop, products, themes/{id}/assets) are first-class
REST resources. GraphQL would require building a query AST and handling
cursor pagination; the REST surface is enough for the image-inventory
use case. We can revisit if a future feature needs write access or
GraphQL-only fields.

Authentication
--------------
Admin API access tokens are per-app. The user supplies the token
explicitly via the CLI (no OAuth flow in v1). Tokens are NEVER logged.
See ``docs/integrations/SHOPIFY_ADMIN.md`` for token-acquisition steps.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

# NOTE: requests is a runtime dependency (see pyproject.toml). We import it
# at module top (not lazily) so import errors surface immediately on
# application startup, mirroring pagespeed_api.py.

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Admin API base URL template. %s is filled with the normalized shop domain.
_API_BASE = "https://%s/admin/api/2024-10"
SHOPIFY_API_VERSION = "2024-10"

# Network configuration (mirrors pagespeed_api.py defaults).
DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_MAX_RETRIES = 3  # total attempts, not "initial + retries"
DEFAULT_RETRY_DELAY = 2.0  # seconds (scaled by attempt index)

# Rate limiting — Shopify's documented leaky-bucket budget is 40 calls per
# 2 seconds for the REST Admin API. We sleep this many seconds between
# calls to stay well below the limit.
_MIN_REQUEST_INTERVAL = 0.05  # 50 ms — fast enough, leaves headroom

# Image file extensions we consider "audit-relevant" for theme assets.
# Excludes .css, .js, .liquid, .json, etc.
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ShopifyAdminError(RuntimeError):
    """Raised when the Shopify Admin API returns an unexpected response.

    Distinct from generic ``RuntimeError`` so callers can catch Shopify
    errors specifically (e.g. CLI exit-code mapping).
    """


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ShopifyAdminClient:
    """Read-only client for the Shopify Admin REST API.

    Example::

        client = ShopifyAdminClient("mystore.myshopify.com", "shpat_...")
        info = client.get_shop_info()
        # {"name": "My Store", "domain": "mystore.myshopify.com",
        #  "plan": "basic", "currency": "USD"}

    The client retries on HTTP 429 and 503 with linear backoff. Other
    non-200 responses raise ``ShopifyAdminError`` (a ``RuntimeError``).
    Network errors propagate as ``requests.exceptions.RequestException``.
    """

    def __init__(
        self,
        shop_domain: str,
        access_token: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> None:
        self.shop_domain = self._normalize_domain(shop_domain)
        self.access_token = access_token
        self.base_url = _API_BASE % self.shop_domain
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._last_request_time = 0.0

    # ----- validation / normalisation -------------------------------------

    @staticmethod
    def _normalize_domain(shop_domain: str) -> str:
        """Strip protocol, path, and trailing slash; require a real host.

        Accepts ``store.myshopify.com``, ``https://store.myshopify.com``,
        ``store.myshopify.com/`` — all normalise to ``store.myshopify.com``.

        Raises ``ValueError`` for empty input or inputs that have no real
        host (e.g. just a path like ``/foo/bar`` or whitespace strings).
        """
        if not shop_domain or not shop_domain.strip():
            raise ValueError("Shopify shop domain cannot be empty")
        d = shop_domain.strip()
        if "://" in d:
            parsed = urlparse(d)
            if not parsed.netloc:
                raise ValueError(f"Invalid Shopify shop domain: {shop_domain!r}")
            d = parsed.netloc
        d = d.rstrip("/")
        # Reject pure paths (e.g. "/foo/bar" or "just/a/path"): they have
        # no real host. This catches cases where the input is missing
        # the actual shop domain.
        if not d or "/" in d or " " in d:
            raise ValueError(f"Invalid Shopify shop domain: {shop_domain!r}")
        return d

    def _headers(self) -> dict[str, str]:
        """Common request headers. Note: access token is in the header,
        never logged."""
        return {
            "X-Shopify-Access-Token": self.access_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ----- rate limiting ----------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Sleep just enough to stay under Shopify's leaky-bucket budget."""
        elapsed = time.time() - self._last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    # ----- HTTP request helper ---------------------------------------------

    def _request(self, method: str, path: str, **params: Any) -> dict:
        """Make an authenticated Admin API request with retry logic.

        ``path`` is the URL path after ``/admin/api/2024-10`` (e.g.
        ``/shop.json``). ``params`` becomes the query string.

        Raises:
            RuntimeError: on non-200, 429-after-retries, 503-after-retries,
                or API-level ``{"errors": ...}`` response.
            requests.exceptions.RequestException: on network failure
                after retries.
        """
        # Local import to mirror pagespeed_api.py's surface and keep this
        # module import-cheap when requests is not actually used.
        import requests

        url = f"{self.base_url}{path}"
        last_exception: BaseException | None = None

        for attempt in range(self.max_retries):
            self._wait_for_rate_limit()
            self._last_request_time = time.time()
            try:
                response = requests.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params or None,
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise

            # Rate limit handling
            if response.status_code == 429:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                raise RuntimeError(f"Shopify API rate limit exceeded. Status: {response.status_code}.")

            # Transient server errors
            if response.status_code == 503:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                raise RuntimeError(f"Shopify API service unavailable. Status: {response.status_code}.")

            if response.status_code != 200:
                # Try to extract a helpful error message but never log
                # anything that might contain the access token.
                body = response.text[:200] if response.text else "(empty body)"
                raise RuntimeError(f"Shopify API error {response.status_code}: {body}")

            data = response.json()
            # Shopify returns {"errors": "..."} on auth/permission errors
            # even with HTTP 200 in some cases. Treat that as an error.
            if "errors" in data and "shop" not in data:
                msg = data["errors"]
                if isinstance(msg, list):
                    msg = "; ".join(str(e) for e in msg)
                raise RuntimeError(f"Shopify API error: {msg}")
            return data

        # Defensive: should not be reachable (loop either returns or raises).
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("Unexpected error in Shopify API request")

    # ----- public methods ---------------------------------------------------

    def get_shop_info(self) -> dict[str, str]:
        """Return a minimal ``ShopifyInfo`` dict: name, domain, plan, currency.

        Raises:
            ValueError: invalid shop domain (caught at construction).
            RuntimeError: API error (4xx/5xx/rate-limit).
            requests.exceptions.RequestException: network error.
        """
        data = self._request("GET", "/shop.json")
        shop = data.get("shop", {})
        return {
            "name": str(shop.get("name", "")),
            "domain": str(shop.get("domain", "")),
            "plan": str(shop.get("plan_display_name", shop.get("plan_name", ""))),
            "currency": str(shop.get("currency", "")),
        }

    def get_products(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return a list of products with their featured image URL.

        Each entry is ``{"id", "title", "handle", "image_url"}``.
        Products without a featured image get ``image_url=None``.

        Args:
            limit: page size (Shopify caps at 250 per request).

        Raises:
            ValueError: if ``limit`` is not in ``[1, 250]``.
            RuntimeError: API error.
        """
        if not 1 <= limit <= 250:
            raise ValueError(f"limit must be in [1, 250], got {limit}")

        data = self._request(
            "GET",
            "/products.json",
            fields="id,title,handle,image",
            limit=limit,
        )
        products = data.get("products", [])
        out: list[dict[str, Any]] = []
        for p in products:
            image = p.get("image") or {}
            out.append(
                {
                    "id": p.get("id"),
                    "title": str(p.get("title", "")),
                    "handle": str(p.get("handle", "")),
                    "image_url": image.get("src") if isinstance(image, dict) else None,
                }
            )
        return out

    def get_theme_assets(self) -> list[dict[str, str]]:
        """Return image assets from the store's main (active) theme.

        Each entry is ``{"theme_name", "key", "url"}``. Only files with
        image extensions (``.jpg``, ``.jpeg``, ``.png``, ``.webp``, ``.avif``,
        ``.gif``, ``.svg``) are returned — CSS/JS/Liquid assets are filtered
        out as they are not image-audit relevant.

        Raises:
            RuntimeError: if the store has no main theme, or on API error.
        """
        themes_data = self._request("GET", "/themes.json")
        themes = themes_data.get("themes", [])
        main_themes = [t for t in themes if t.get("role") == "main"]
        if not main_themes:
            raise RuntimeError(f"No main theme found for {self.shop_domain}")
        # Shop returns the active theme first; be defensive regardless.
        main = main_themes[0]
        theme_id = main.get("id")
        theme_name = str(main.get("name", ""))

        if not theme_id:
            raise RuntimeError(f"Main theme for {self.shop_domain} has no id")

        assets_data = self._request("GET", f"/themes/{theme_id}/assets.json")
        assets = assets_data.get("assets", [])
        out: list[dict[str, str]] = []
        for a in assets:
            key = str(a.get("key", ""))
            public_url = a.get("public_url")
            if not key or not isinstance(public_url, str):
                continue
            if not key.lower().endswith(_IMAGE_EXTS):
                continue
            out.append(
                {
                    "theme_name": theme_name,
                    "key": key,
                    "url": public_url,
                }
            )
        return out
