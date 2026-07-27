"""
Tests for PageSpeed Insights API client.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import responses

from integrations.pagespeed_api import (
    PageSpeedAPIClient,
    PageSpeedMetrics,
    get_pagespeed_metrics,
)


# --- Fixtures ----------------------------------------------------------------


@responses.activate
def test_get_metrics_success():
    """Test successful API response parsing."""
    # Mock API response
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "audits": {
                "largest-contentful-paint": {
                    "numericValue": 2500,  # 2.5 seconds in ms
                },
                "cumulative-layout-shift": {
                    "numericValue": 0.1,
                },
                "interaction-to-next-paint": {
                    "numericValue": 200,  # 0.2 seconds in ms
                },
                "first-contentful-paint": {
                    "numericValue": 1200,  # 1.2 seconds in ms
                },
                "first-meaningful-paint": {
                    "numericValue": 1500,  # 1.5 seconds in ms
                },
                "speed-index": {
                    "numericValue": 1800,  # 1.8 seconds in ms
                },
                "interactive": {
                    "numericValue": 3500,  # 3.5 seconds in ms
                },
                "total-blocking-time": {
                    "numericValue": 150,  # 150 ms
                },
                "performance": {
                    "score": 0.75,  # 75/100
                },
            },
        },
        "loadingExperience": {},
    }
    
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json=mock_response,
        status=200,
    )
    
    client = PageSpeedAPIClient()
    metrics = client.get_metrics("https://example.com", strategy="mobile")
    
    assert isinstance(metrics, PageSpeedMetrics)
    assert metrics.url == "https://example.com"
    assert metrics.strategy == "mobile"
    assert metrics.lcp == 2.5  # 2500ms -> 2.5s
    assert metrics.cls == 0.1
    assert metrics.inp == 0.2  # 200ms -> 0.2s
    assert metrics.first_contentful_paint == 1.2
    assert metrics.first_meaningful_paint == 1.5
    assert metrics.speed_index == 1.8
    assert metrics.time_to_interactive == 3.5
    assert metrics.total_blocking_time == 150
    assert metrics.performance_score == 75


@responses.activate
def test_get_metrics_missing_metrics():
    """Test handling of missing metrics in response."""
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "audits": {
                "performance": {
                    "score": 0.5,
                },
            },
        },
    }
    
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json=mock_response,
        status=200,
    )
    
    client = PageSpeedAPIClient()
    metrics = client.get_metrics("https://example.com")
    
    # Missing metrics should have default values
    assert metrics.lcp == 0.0
    assert metrics.cls == 0.0
    assert metrics.inp is None
    assert metrics.performance_score == 50


@responses.activate
def test_get_metrics_desktop_strategy():
    """Test desktop strategy."""
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "audits": {
                "largest-contentful-paint": {"numericValue": 1500},
                "performance": {"score": 0.9},
            },
        },
    }
    
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json=mock_response,
        status=200,
    )
    
    client = PageSpeedAPIClient()
    metrics = client.get_metrics("https://example.com", strategy="desktop")
    
    assert metrics.strategy == "desktop"
    assert metrics.lcp == 1.5
    assert metrics.performance_score == 90


def test_get_metrics_invalid_url():
    """Test error handling for invalid URL."""
    client = PageSpeedAPIClient()
    
    with pytest.raises(ValueError, match="URL cannot be empty"):
        client.get_metrics("")


def test_get_metrics_invalid_strategy():
    """Test error handling for invalid strategy."""
    client = PageSpeedAPIClient()
    
    with pytest.raises(ValueError, match="Strategy must be"):
        client.get_metrics("https://example.com", strategy="tablet")


def test_get_metrics_url_normalization():
    """Test URL normalization (adding https://)."""
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "audits": {
                "performance": {"score": 0.8},
            },
        },
    }
    
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            json=mock_response,
            status=200,
        )
        
        client = PageSpeedAPIClient()
        # URL without scheme should be normalized
        metrics = client.get_metrics("example.com")
        
        # Check that the URL was normalized
        assert metrics.url == "https://example.com"


@responses.activate
def test_get_metrics_api_error():
    """Test handling of API error response."""
    error_response = {
        "error": {
            "code": 400,
            "message": "Invalid URL",
        }
    }
    
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json=error_response,
        status=400,
    )
    
    client = PageSpeedAPIClient()
    
    with pytest.raises(RuntimeError, match="PageSpeed API error"):
        client.get_metrics("https://example.com")


@responses.activate
def test_get_metrics_rate_limit():
    """Test handling of rate limit (HTTP 429)."""
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        status=429,
    )
    
    client = PageSpeedAPIClient(max_retries=1)  # Only 1 attempt
    
    with pytest.raises(RuntimeError, match="rate limit exceeded"):
        client.get_metrics("https://example.com")


@responses.activate
def test_get_metrics_server_error():
    """Test handling of server error (HTTP 500)."""
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        status=500,
        body="Internal Server Error",
    )
    
    client = PageSpeedAPIClient(max_retries=1)
    
    with pytest.raises(RuntimeError, match="PageSpeed API error"):
        client.get_metrics("https://example.com")


@responses.activate
def test_get_metrics_with_api_key():
    """Test request with API key."""
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "audits": {
                "performance": {"score": 0.95},
            },
        },
    }
    
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json=mock_response,
        status=200,
    )
    
    client = PageSpeedAPIClient(api_key="test-api-key")
    metrics = client.get_metrics("https://example.com")
    
    assert metrics.performance_score == 95


def test_to_dict():
    """Test conversion to dictionary."""
    metrics = PageSpeedMetrics(
        url="https://example.com",
        strategy="mobile",
        fetch_time="2024-01-15T10:30:00.000Z",
        lcp=2.5,
        cls=0.1,
        inp=0.2,
        first_contentful_paint=1.2,
        first_meaningful_paint=1.5,
        speed_index=1.8,
        time_to_interactive=3.5,
        total_blocking_time=150,
        performance_score=75,
    )
    
    result = metrics.to_dict()
    
    assert result["url"] == "https://example.com"
    assert result["strategy"] == "mobile"
    assert result["metrics"]["lcp"] == 2.5
    assert result["metrics"]["cls"] == 0.1
    assert result["performance_score"] == 75


@responses.activate
def test_convenience_function():
    """Test the convenience function get_pagespeed_metrics."""
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "audits": {
                "largest-contentful-paint": {"numericValue": 2000},
                "performance": {"score": 0.8},
            },
        },
    }
    
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json=mock_response,
        status=200,
    )
    
    metrics = get_pagespeed_metrics("https://example.com")
    
    assert isinstance(metrics, PageSpeedMetrics)
    assert metrics.lcp == 2.0
    assert metrics.performance_score == 80


def test_rate_limiting():
    """Test that rate limiting is enforced."""
    import time as time_module
    
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "audits": {
                "performance": {"score": 0.8},
            },
        },
    }
    
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            json=mock_response,
            status=200,
        )
        rsps.add(
            responses.GET,
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            json=mock_response,
            status=200,
        )
        
        client = PageSpeedAPIClient()
        
        # First request
        start_time = time_module.time()
        client.get_metrics("https://example1.com")
        first_time = time_module.time()
        
        # Second request should wait at least 1 second
        client.get_metrics("https://example2.com")
        second_time = time_module.time()
        
        # Should have waited at least the minimum interval
        assert second_time - first_time >= 0.9  # Allow small tolerance


@responses.activate
def test_retry_on_failure():
    """Test retry mechanism on failure."""
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "audits": {
                "performance": {"score": 0.8},
            },
        },
    }
    
    # First two requests fail, third succeeds
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        status=503,
    )
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        status=503,
    )
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json=mock_response,
        status=200,
    )
    
    client = PageSpeedAPIClient(max_retries=3, retry_delay=0.1)
    metrics = client.get_metrics("https://example.com")
    
    assert metrics.performance_score == 80


@responses.activate
def test_retry_exhausted():
    """Test that retry exhaustion raises error."""
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        status=503,
    )
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        status=503,
    )
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        status=503,
    )
    
    client = PageSpeedAPIClient(max_retries=3, retry_delay=0.1)
    
    with pytest.raises(RuntimeError, match="rate limit exceeded"):
        client.get_metrics("https://example.com")
