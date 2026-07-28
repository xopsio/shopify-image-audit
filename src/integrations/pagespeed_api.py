"""
Google PageSpeed Insights API client for Shopify Image Audit.

Provides live LCP, CLS, and INP metrics for Shopify stores.
Used by the `audit measure` CLI command.

API Documentation: https://developers.google.com/speed/docs/insights/v5/reference
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests


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
    inp: Optional[float]  # Interaction to Next Paint (seconds) - may be None for some runs
    
    # Additional performance metrics
    first_contentful_paint: float  # FCP (seconds)
    first_meaningful_paint: Optional[float]  # FMP (seconds)
    speed_index: float  # Speed Index (seconds)
    time_to_interactive: float  # TTI (seconds)
    total_blocking_time: float  # TBT (milliseconds)
    
    # Score (0-100)
    performance_score: int
    
    # Metadata
    url: str
    strategy: str  # "mobile" or "desktop"
    fetch_time: str  # ISO timestamp of when the test was run
    
    def to_dict(self) -> dict:
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
        api_key: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        retry_delay: float = RETRY_DELAY,
    ):
        """
        Initialize the PageSpeed API client.
        
        Args:
            api_key: Optional Google Cloud API key. Not required for basic use.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts.
            retry_delay: Delay between retries in seconds.
        """
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
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
    
    def _build_params(self, url: str, strategy: str = "mobile") -> dict:
        """Build query parameters for the API request."""
        params = {
            "url": url,
            "category": "performance",  # Only fetch performance metrics
            "strategy": strategy,  # mobile or desktop
        }
        if self.api_key:
            params["key"] = self.api_key
        return params
    
    def _parse_response(self, data: dict, url: str, strategy: str) -> PageSpeedMetrics:
        """Parse API response into structured metrics."""
        lighthouse_result = data.get("lighthouseResult", {})
        
        # Extract metrics from lighthouseResult
        metrics = lighthouse_result.get("audits", {})
        
        def get_metric_value(name: str, default: float = 0.0) -> float:
            """Extract a metric value from audits."""
            audit = metrics.get(name, {})
            if not audit:
                return default
            numeric_value = audit.get("numericValue")
            if numeric_value is not None:
                return float(numeric_value)
            return default
        
        def get_score(name: str, default: int = 0) -> int:
            """Extract a score value from audits."""
            audit = metrics.get(name, {})
            if not audit:
                return default
            score = audit.get("score")
            if score is not None:
                return int(float(score) * 100)
            return default
        
        # Get fetch time
        fetch_time = lighthouse_result.get("fetchTime", "")
        
        # Core Web Vitals (in seconds, except CLS which is unitless 0-1)
        lcp = get_metric_value("largest-contentful-paint", 0.0) / 1000  # ms to s
        cls = get_metric_value("cumulative-layout-shift", 0.0)
        inp = get_metric_value("interaction-to-next-paint")
        if inp > 0:
            inp = inp / 1000  # ms to s
        else:
            inp = None
        
        # Additional metrics
        fcp = get_metric_value("first-contentful-paint", 0.0) / 1000
        fmp = get_metric_value("first-meaningful-paint")
        if fmp > 0:
            fmp = fmp / 1000
        else:
            fmp = None
        
        speed_index = get_metric_value("speed-index", 0.0) / 1000
        tti = get_metric_value("interactive", 0.0) / 1000
        tbt = get_metric_value("total-blocking-time", 0.0)  # already in ms
        
        # Performance score (0-100)
        performance_score = get_score("performance", 0)
        
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
        if not url:
            raise ValueError("URL cannot be empty")
        
        if strategy not in ("mobile", "desktop"):
            raise ValueError(f"Strategy must be 'mobile' or 'desktop', got '{strategy}'")
        
        # Normalize URL
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        
        # Rate limiting
        self._wait_for_rate_limit()
        
        # Build request
        params = self._build_params(url, strategy)
        
        # Make request with retries
        last_exception: Optional[Exception] = None
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
                        f"PageSpeed API service unavailable. Status: {response.status_code}. "
                        f"Please try again later."
                    )
                
                # Check for other errors
                if response.status_code != 200:
                    error_msg = self._get_error_message(response)
                    raise RuntimeError(
                        f"PageSpeed API error: {response.status_code} - {error_msg}"
                    )
                
                # Parse response
                data = response.json()
                
                # Check for API-specific errors
                if "error" in data:
                    error_msg = data["error"].get("message", "Unknown error")
                    raise RuntimeError(f"PageSpeed API error: {error_msg}")
                
                return self._parse_response(data, url, strategy)
                
            except requests.exceptions.Timeout:
                last_exception = requests.exceptions.Timeout(
                    f"Request timed out after {self.timeout} seconds"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise last_exception
                
            except requests.exceptions.RequestException as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise
        
        # Should not reach here, but just in case
        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected error in PageSpeed API request")
    
    def _get_error_message(self, response: requests.Response) -> str:
        """Extract error message from response."""
        try:
            data = response.json()
            if "error" in data:
                return data["error"].get("message", "Unknown error")
        except Exception:
            pass
        return response.text[:200] if response.text else "No error message"


# --- Convenience Function ----------------------------------------------------


def get_pagespeed_metrics(
    url: str,
    strategy: str = "mobile",
    api_key: Optional[str] = None,
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
