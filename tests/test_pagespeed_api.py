"""
Tests for PageSpeed Insights API client.
"""

from __future__ import annotations

import pytest
import responses

from integrations.pagespeed_api import (
    PageSpeedAPIClient,
    PageSpeedMetrics,
)

# --- Helper for mock responses -------------------------------------------------

def _make_mock_response(performance_score: float = 0.75) -> dict:
    """Create a standard mock API response."""
    return {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "categories": {
                "performance": {
                    "score": performance_score,
                }
            },
            "audits": {
                "largest-contentful-paint": {"numericValue": 2500},
                "cumulative-layout-shift": {"numericValue": 0.1},
                "interaction-to-next-paint": {"numericValue": 200},
                "first-contentful-paint": {"numericValue": 1200},
                "first-meaningful-paint": {"numericValue": 1500},
                "speed-index": {"numericValue": 1800},
                "interactive": {"numericValue": 3500},
                "total-blocking-time": {"numericValue": 150},
            },
        },
    }


# --- Tests --------------------------------------------------------------------


@responses.activate
def test_get_metrics_success():
    """Test successful API response parsing."""
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json=_make_mock_response(0.75),
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
def test_get_metrics_performance_score_from_categories():
    """Test that performance score is read from categories, not audits."""
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "categories": {
                "performance": {
                    "score": 0.85,
                }
            },
            "audits": {},
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

    assert metrics.performance_score == 85


@responses.activate
def test_get_metrics_missing_metrics():
    """Test handling of missing metrics in response."""
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "categories": {
                "performance": {
                    "score": 0.5,
                }
            },
            "audits": {},
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
            "categories": {
                "performance": {
                    "score": 0.9,
                }
            },
            "audits": {
                "largest-contentful-paint": {"numericValue": 1500},
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


def test_get_metrics_hostless_url():
    """Test error handling for hostless URL."""
    client = PageSpeedAPIClient()

    with pytest.raises(ValueError, match="URL must include a hostname"):
        client.get_metrics("https://")


def test_get_metrics_invalid_strategy():
    """Test error handling for invalid strategy."""
    client = PageSpeedAPIClient()

    with pytest.raises(ValueError, match="Strategy must be"):
        client.get_metrics("https://example.com", strategy="tablet")


@responses.activate
def test_get_metrics_url_normalization():
    """Test URL normalization (adding https://)."""
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json=_make_mock_response(0.8),
        status=200,
    )

    client = PageSpeedAPIClient()
    # URL without scheme should be normalized
    metrics = client.get_metrics("example.com")

    # Check that the URL was normalized
    assert metrics.url == "https://example.com"
    assert metrics.performance_score == 80


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
def test_get_metrics_service_unavailable():
    """Test handling of service unavailable (HTTP 503)."""
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        status=503,
    )

    client = PageSpeedAPIClient(max_retries=1)  # Only 1 attempt

    with pytest.raises(RuntimeError, match="service unavailable"):
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
    """Test request with API key and verify it's sent in the request."""
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "categories": {
                "performance": {
                    "score": 0.95,
                }
            },
            "audits": {},
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

    # Verify the API key was sent in the request
    assert len(responses.calls) == 1
    assert "key=test-api-key" in responses.calls[0].request.url
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
def test_strategy_param_in_request():
    """Test that strategy parameter is included in API request."""
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json=_make_mock_response(0.8),
        status=200,
    )

    client = PageSpeedAPIClient()
    metrics = client.get_metrics("https://example.com", strategy="desktop")

    # Verify the request was made with strategy parameter
    assert len(responses.calls) == 1
    assert "strategy=desktop" in responses.calls[0].request.url
    assert metrics.strategy == "desktop"


@responses.activate
def test_retry_on_failure():
    """Test retry mechanism on failure."""
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
        json=_make_mock_response(0.8),
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

    with pytest.raises(RuntimeError, match="service unavailable"):
        client.get_metrics("https://example.com")
