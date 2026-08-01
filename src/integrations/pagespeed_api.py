"""
Google PageSpeed Insights API client for Shopify Image Audit.

Provides live LCP, CLS, and INP metrics for Shopify stores.
Used by the `audit measure` CLI command.

API Documentation: https://developers.google.com/speed/docs/insights/v5/reference
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

import requests

from engine._logging import get_logger

if TYPE_CHECKING:
    from integrations._cache import ResponseCache

_log = get_logger()

# --- Constants ---------------------------------------------------------------

PSI_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
# Free tier: no API key required for basic use, but rate limited
# With API key: higher limits (see Google Cloud Console)
DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_RETRIES = 3
RETRY_DELAY = 2  # seconds between retries


# --- Data Classes -------------------------------------------------------------


@dataclass
class PageSpeedMetrics:
    """Structured metrics from PageSpeed Insights API."""

    # Core Web Vitals
    lcp: float  # Largest Contentful Paint (seconds)
    cls: float  # Cumulative Layout Shift (score 0-1)
    inp: float | None  # Interaction to Next Paint (seconds) - may be None for some runs

    # Additional performance metrics
    first_contentful_paint: float  # FCP (seconds)
    first_meaningful_paint: float | None  # FMP (seconds)
    speed_index: float  # Speed Index (seconds)
    time_to_interactive: float  # TTI (seconds)
    total_blocking_time: float  # TBT (milliseconds)

    # Score (0-100)
    performance_score: int

    # Metadata
    url: str
    strategy: str  # "mobile" or "desktop"
    fetch_time: str  # ISO timestamp of when the test was run

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "url": self.url,
            "strategy": self.strategy,
            "fetch_time": self.fetch_time,
            "metrics": {
                "lcp": self.lcp,
                "cls": self.cls,
                "inp": self.inp,
                "first_contentful_paint": self.first_contentful_paint,
                "first_meaningful_paint": self.first_meaningful_paint,
                "speed_index": self.speed_index,
                "time_to_interactive": self.time_to_interactive,
                "total_blocking_time": self.total_blocking_time,
            },
            "performance_score": self.performance_score,
        }


# --- API Client ---------------------------------------------------------------


class PageSpeedAPIClient:
    """
    Client for Google PageSpeed Insights API.

    Handles rate limiting, retries, and error responses.

    Example:
        client = PageSpeedAPIClient()
        metrics = client.get_metrics("https://example.myshopify.com", strategy="mobile")
        print(f"LCP: {metrics.lcp}s")
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        retry_delay: float = RETRY_DELAY,
        cache: ResponseCache | None = None,
    ):
        """
        Initialize the PageSpeed API client.

        Args:
            api_key: Optional Google Cloud API key. Not required for basic use.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts.
            retry_delay: Delay between retries in seconds.
            cache: Optional :class:`~integrations._cache.ResponseCache`.
                When provided, successful responses are cached and served
                from cache within the TTL. Pass ``None`` to disable.
        """
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._cache = cache
        self._last_request_time: float = 0

        # Rate limiting: Google recommends at least 1 second between requests
        # Without API key: ~20 requests per minute limit
        # With API key: higher limits
        self._min_request_interval = 1.0  # seconds

    def _wait_for_rate_limit(self) -> None:
        """Wait if necessary to respect rate limits."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)

    def _build_params(self, url: str, strategy: str = "mobile") -> dict[str, str]:
        """Build query parameters for the API request."""
        params: dict[str, str] = {
            "url": url,
            "category": "performance",  # Only fetch performance metrics
            "strategy": strategy,  # mobile or desktop
        }
        if self.api_key:
            params["key"] = self.api_key
        return params

    def _parse_response(self, data: dict[str, Any], url: str, strategy: str) -> PageSpeedMetrics:
        """Parse API response into structured metrics."""
        lighthouse_result = data.get("lighthouseResult", {})

        # Extract metrics from lighthouseResult
        metrics = lighthouse_result.get("audits", {})

        # Get performance score from categories, not audits
        categories = lighthouse_result.get("categories", {})
        performance_category = categories.get("performance", {})
        performance_score_raw = performance_category.get("score")
        performance_score = int(float(performance_score_raw) * 100) if performance_score_raw is not None else 0

        def get_metric_value(name: str, default: float = 0.0) -> float:
            """Extract a metric value from audits."""
            audit = metrics.get(name, {})
            if not audit:
                return default
            numeric_value = audit.get("numericValue")
            if numeric_value is not None:
                return float(numeric_value)
            return default

        # Get fetch time
        fetch_time = lighthouse_result.get("fetchTime", "")

        # Core Web Vitals (in seconds, except CLS which is unitless 0-1)
        lcp = get_metric_value("largest-contentful-paint", 0.0) / 1000  # ms to s
        cls = get_metric_value("cumulative-layout-shift", 0.0)
        # INP may be absent from the response: get_metric_value yields 0.0
        # then, which maps to None (absent, not zero).
        inp_raw = get_metric_value("interaction-to-next-paint")
        inp: float | None = inp_raw / 1000 if inp_raw > 0 else None

        # Additional metrics
        fcp = get_metric_value("first-contentful-paint", 0.0) / 1000
        # Same absent-vs-zero mapping for FMP.
        fmp_raw = get_metric_value("first-meaningful-paint")
        fmp: float | None = fmp_raw / 1000 if fmp_raw > 0 else None

        speed_index = get_metric_value("speed-index", 0.0) / 1000
        tti = get_metric_value("interactive", 0.0) / 1000
        tbt = get_metric_value("total-blocking-time", 0.0)  # already in ms

        return PageSpeedMetrics(
            url=url,
            strategy=strategy,
            fetch_time=fetch_time,
            lcp=lcp,
            cls=cls,
            inp=inp,
            first_contentful_paint=fcp,
            first_meaningful_paint=fmp,
            speed_index=speed_index,
            time_to_interactive=tti,
            total_blocking_time=tbt,
            performance_score=performance_score,
        )

    def _validate_url(self, url: str) -> str:
        """Validate and normalize URL. Raises ValueError for invalid URLs."""
        if not url or not url.strip():
            raise ValueError("URL cannot be empty")

        url = url.strip()
        parsed = urlparse(url)

        # If scheme is provided, it must be http or https
        if parsed.scheme and parsed.scheme not in ("http", "https"):
            raise ValueError(f"URL scheme must be http or https, got '{parsed.scheme}'")

        # For scheme-less URLs, we need a non-empty string that's not just a path
        # (e.g., "example.com" is valid, "/path" or "https://" is not)
        if not parsed.scheme:
            # Must have something that looks like a hostname
            if not url or url.startswith("/") or "://" in url:
                raise ValueError("URL must include a hostname")
        else:
            # For URLs with scheme, must have a netloc (hostname)
            if not parsed.netloc:
                raise ValueError("URL must include a hostname")

        # Normalize scheme-less URLs
        if not parsed.scheme:
            url = f"https://{url}"

        return url

    def get_metrics(
        self,
        url: str,
        strategy: str = "mobile",
    ) -> PageSpeedMetrics:
        """
        Fetch PageSpeed metrics for a given URL.

        Args:
            url: The URL to analyze (e.g., "https://example.myshopify.com")
            strategy: "mobile" or "desktop"

        Returns:
            PageSpeedMetrics with all performance data.

        Raises:
            ValueError: If the URL is invalid or strategy is not supported.
            requests.exceptions.RequestException: If the API request fails.
            RuntimeError: If the API returns an error or rate limit is hit.
        """
        # Validate inputs
        if strategy not in ("mobile", "desktop"):
            raise ValueError(f"Strategy must be 'mobile' or 'desktop', got '{strategy}'")

        # Validate and normalize URL
        url = self._validate_url(url)

        # Check cache before hitting the network.
        if self._cache is not None:
            cached = self._cache.get(url, strategy)
            if cached is not None:
                return self._parse_response(cached, url, strategy)

        # Rate limiting
        self._wait_for_rate_limit()

        # Build request
        params = self._build_params(url, strategy)

        # Make request with retries
        last_exception: Exception | None = None
        _log.info("PageSpeed request: url=%s strategy=%s attempt=1/%d", url, strategy, self.max_retries)
        for attempt in range(self.max_retries):
            try:
                self._last_request_time = time.time()
                response = requests.get(
                    PSI_API_URL,
                    params=params,
                    timeout=self.timeout,
                )

                # Check for rate limiting (HTTP 429)
                if response.status_code == 429:
                    if attempt < self.max_retries - 1:
                        _log.debug("PageSpeed 429: retrying (attempt %d)", attempt + 1)
                        time.sleep(self.retry_delay * (attempt + 1))
                        continue
                    raise RuntimeError(
                        f"PageSpeed API rate limit exceeded. Status: {response.status_code}. "
                        f"Please wait before making more requests."
                    )

                # Check for service unavailable (HTTP 503)
                if response.status_code == 503:
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (attempt + 1))
                        continue
                    raise RuntimeError(
                        f"PageSpeed API service unavailable. Status: {response.status_code}. Please try again later."
                    )

                # Check for other errors
                if response.status_code != 200:
                    error_msg = self._get_error_message(response)
                    raise RuntimeError(f"PageSpeed API error: {response.status_code} - {error_msg}")

                # Parse response
                data = response.json()

                # Check for API-specific errors
                if "error" in data:
                    error_msg = data["error"].get("message", "Unknown error")
                    raise RuntimeError(f"PageSpeed API error: {error_msg}")

                # Cache the successful response for future calls.
                if self._cache is not None:
                    self._cache.set(url, strategy, data)

                return self._parse_response(data, url, strategy)

            except requests.exceptions.Timeout:
                last_exception = requests.exceptions.Timeout(f"Request timed out after {self.timeout} seconds")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise last_exception from None

            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
                # requests embeds the full request URL (including ?key=...) in
                # connection-error text — strip the key before it surfaces.
                raise RuntimeError(self._redact_message(str(e))) from None

        # Should not reach here, but just in case
        if last_exception:
            raise RuntimeError(self._redact_message(str(last_exception))) from None
        raise RuntimeError("Unexpected error in PageSpeed API request")

    def _redact_message(self, text: str) -> str:
        """Remove the API key from an error message.

        Connection errors include the full request URL in their text; the
        key must never appear in CLI output or logs.
        """
        if not self.api_key:
            return text
        redacted = text.replace(self.api_key, "***")
        # Also cover the percent-encoded form used in query strings.
        encoded_key = quote(self.api_key, safe="")
        return redacted.replace(encoded_key, "***")

    def _get_error_message(self, response: requests.Response) -> str:
        """Extract error message from response."""
        try:
            data: dict[str, Any] = response.json()
            if "error" in data:
                return str(data["error"].get("message", "Unknown error"))
        except Exception:
            pass
        return response.text[:200] if response.text else "No error message"


# --- Convenience Function ----------------------------------------------------


def get_pagespeed_metrics(
    url: str,
    strategy: str = "mobile",
    api_key: str | None = None,
) -> PageSpeedMetrics:
    """
    Convenience function to fetch PageSpeed metrics.

    Args:
        url: The URL to analyze.
        strategy: "mobile" or "desktop".
        api_key: Optional Google Cloud API key.

    Returns:
        PageSpeedMetrics with all performance data.

    Example:
        metrics = get_pagespeed_metrics("https://example.myshopify.com")
        print(f"LCP: {metrics.lcp:.2f}s, Performance Score: {metrics.performance_score}")
    """
    client = PageSpeedAPIClient(api_key=api_key)
    return client.get_metrics(url, strategy=strategy)


def fetch_lighthouse_json(
    url: str,
    strategy: str = "mobile",
    api_key: str | None = None,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_RETRIES,
    cache: ResponseCache | None = None,
) -> dict[str, Any]:
    """
    Fetch a full Lighthouse JSON report for ``url`` from the PageSpeed Insights API.

    Returns the raw ``lighthouseResult`` dict (same shape as a Lighthouse CLI
    ``--output=json`` artifact). Suitable for passing directly to
    ``engine.audit_orchestrator.run_audit`` via a temporary file, or for any
    consumer that wants the raw audit payload rather than the parsed
    ``PageSpeedMetrics``.

    Raises:
        ValueError: bad URL / strategy.
        RuntimeError: API error or rate limit.
        requests.exceptions.RequestException: network failure after retries.
    """
    if strategy not in ("mobile", "desktop"):
        raise ValueError(f"Strategy must be 'mobile' or 'desktop', got '{strategy}'")

    # Build a one-shot client with explicit timeout/retries so the caller can
    # dial them without instantiating PageSpeedAPIClient themselves.
    client = PageSpeedAPIClient(
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
    )
    # Validate + normalise the URL (raises ValueError on bad input).
    url = client._validate_url(url)

    # Consult cache before any network I/O.
    if cache is not None:
        cached = cache.get(url, strategy)
        if cached is not None:
            lhr = cached.get("lighthouseResult", cached)
            if isinstance(lhr, dict):
                return lhr

    client._wait_for_rate_limit()

    params = client._build_params(url, strategy)

    last_exception: Exception | None = None
    for attempt in range(client.max_retries):
        try:
            client._last_request_time = time.time()
            response = requests.get(PSI_API_URL, params=params, timeout=client.timeout)

            if response.status_code == 429:
                if attempt < client.max_retries - 1:
                    time.sleep(client.retry_delay * (attempt + 1))
                    continue
                raise RuntimeError(f"PageSpeed API rate limit exceeded. Status: {response.status_code}.")
            if response.status_code == 503:
                if attempt < client.max_retries - 1:
                    time.sleep(client.retry_delay * (attempt + 1))
                    continue
                raise RuntimeError(f"PageSpeed API service unavailable. Status: {response.status_code}.")
            if response.status_code != 200:
                raise RuntimeError(
                    f"PageSpeed API error: {response.status_code} - {client._get_error_message(response)}"
                )

            data = response.json()
            if "error" in data:
                raise RuntimeError(f"PageSpeed API error: {data['error'].get('message', 'Unknown')}")
            lhr = data.get("lighthouseResult")
            if not isinstance(lhr, dict):
                raise RuntimeError("PageSpeed API response missing 'lighthouseResult'")
            # Cache the raw response for future calls.
            if cache is not None:
                cache.set(url, strategy, data)
            return lhr
        except requests.exceptions.RequestException as e:
            last_exception = e
            if attempt < client.max_retries - 1:
                time.sleep(client.retry_delay)
                continue
            raise

    # Defensive — should not be reachable.
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected error in PageSpeed API request")
