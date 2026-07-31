"""
Tests for PageSpeed Insights API client.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests
import responses
from typer.testing import CliRunner

from engine.cli import app
from integrations.pagespeed_api import (
    PageSpeedAPIClient,
    PageSpeedMetrics,
    fetch_lighthouse_json,
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


# --- Tests for fetch_lighthouse_json -----------------------------------------

@responses.activate
def test_fetch_lighthouse_json_returns_lhr_dict():
    """fetch_lighthouse_json must return the inner lighthouseResult dict,
    the same shape as a Lighthouse CLI --output=json artifact."""
    mock_response = {
        "lighthouseResult": {
            "fetchTime": "2024-01-15T10:30:00.000Z",
            "audits": {
                "largest-contentful-paint": {"numericValue": 1500},
            },
            "categories": {
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

    lhr = fetch_lighthouse_json("https://example.com", strategy="mobile")
    assert isinstance(lhr, dict)
    assert "audits" in lhr
    assert "largest-contentful-paint" in lhr["audits"]
    assert lhr["audits"]["largest-contentful-paint"]["numericValue"] == 1500


@responses.activate
def test_fetch_lighthouse_json_sends_strategy():
    """The strategy parameter must propagate to the API request."""
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json={"lighthouseResult": {"audits": {}, "categories": {}}},
        status=200,
    )

    fetch_lighthouse_json("https://example.com", strategy="desktop")
    assert "strategy=desktop" in responses.calls[0].request.url


@responses.activate
def test_fetch_lighthouse_json_invalid_url():
    """Bad URL must raise ValueError without hitting the network."""
    with pytest.raises(ValueError, match="URL"):
        fetch_lighthouse_json("")


@responses.activate
def test_fetch_lighthouse_json_invalid_strategy():
    """Bad strategy must raise ValueError."""
    with pytest.raises(ValueError, match="Strategy"):
        fetch_lighthouse_json("https://example.com", strategy="tablet")


@responses.activate
def test_fetch_lighthouse_json_missing_lhr_field():
    """If the response has no lighthouseResult, raise RuntimeError."""
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json={"kind": "pagespeedonline#result"},  # no lighthouseResult
        status=200,
    )

    with pytest.raises(RuntimeError, match="lighthouseResult"):
        fetch_lighthouse_json("https://example.com", max_retries=1)


@responses.activate
def test_fetch_lighthouse_json_url_normalization():
    """Scheme-less URLs are normalized to https:// before the request."""
    responses.add(
        responses.GET,
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        json={"lighthouseResult": {"audits": {}, "categories": {}}},
        status=200,
    )

    fetch_lighthouse_json("example.com")
    # The URL in the API call must have been normalized.
    assert "url=https%3A%2F%2Fexample.com" in responses.calls[0].request.url


# ---------------------------------------------------------------------------
# Sprint 6 TD-1: Coverage close-out (additional edge-case tests)
# ---------------------------------------------------------------------------

class Test429Retry:
    """429-then-200 retry path: the second attempt's sleep branch."""

    def test_429_then_200_succeeds_after_retry(self) -> None:
        import responses

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.GET,
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                status=429,
            )
            rsps.add(
                responses.GET,
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                json={
                    "lighthouseResult": {
                        "audits": {
                            "largest-contentful-paint": {"numericValue": 1800},
                            "cumulative-layout-shift": {"numericValue": 0.05},
                            "experimental-interaction-to-next-paint": {"numericValue": 120},
                            "server-response-time": {"numericValue": 400},
                        },
                        "categories": {"performance": {"score": 0.95}},
                        "configSettings": {"formFactor": "mobile"},
                        "finalUrl": "https://demo.myshopify.com",
                        "fetchTime": "2026-07-30T15:00:00Z",
                    }
                },
                status=200,
            )
            client = PageSpeedAPIClient(retry_delay=0.0)
            metrics = client.get_metrics("https://demo.myshopify.com")
            assert metrics.lcp == 1.8  # 1800 ms = 1.8 s


class TestTimeoutExhaustion:
    """Timeout across all retries → RuntimeError."""

    def test_timeout_all_retries_exhausted(self) -> None:
        import responses

        with responses.RequestsMock() as rsps:
            for _ in range(3):
                rsps.add(
                    responses.GET,
                    "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                    body=requests.exceptions.Timeout(),
                )
            client = PageSpeedAPIClient(retry_delay=0.0)
            with pytest.raises(requests.exceptions.Timeout):
                client.get_metrics("https://demo.myshopify.com")


class TestGetErrorMessage:
    """_get_error_message: JSON parse fallback and plain text fallback."""

    def test_json_error_field(self) -> None:
        client = PageSpeedAPIClient(retry_delay=0.0)
        resp = MagicMock()
        resp.json.return_value = {"error": {"message": "rate limited"}}
        msg = client._get_error_message(resp)
        assert msg == "rate limited"

    def test_non_json_response_falls_back_to_text(self) -> None:
        client = PageSpeedAPIClient(retry_delay=0.0)
        resp = MagicMock()
        resp.json.side_effect = ValueError("not JSON")
        resp.text = "<html>500 Internal Server Error</html>"
        msg = client._get_error_message(resp)
        assert "500 Internal Server Error" in msg

    def test_empty_response_text(self) -> None:
        client = PageSpeedAPIClient(retry_delay=0.0)
        resp = MagicMock()
        resp.json.side_effect = ValueError
        resp.text = ""
        msg = client._get_error_message(resp)
        assert msg == "No error message"


class TestGetPagespeedMetricsWrapper:
    """The module-level convenience wrapper."""

    @responses.activate
    def test_returns_metrics(self) -> None:
        responses.add(
            responses.GET,
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            json={
                "lighthouseResult": {
                    "audits": {
                        "largest-contentful-paint": {"numericValue": 1500},
                        "cumulative-layout-shift": {"numericValue": 0.04},
                        "experimental-interaction-to-next-paint": {"numericValue": 100},
                        "server-response-time": {"numericValue": 300},
                    },
                    "categories": {"performance": {"score": 0.98}},
                    "configSettings": {"formFactor": "desktop"},
                    "finalUrl": "https://demo.myshopify.com",
                    "fetchTime": "2026-07-30T15:00:00Z",
                }
            },
            status=200,
        )
        from integrations.pagespeed_api import get_pagespeed_metrics
        metrics = get_pagespeed_metrics("https://demo.myshopify.com", strategy="desktop")
        assert metrics.lcp == 1.5  # seconds (1500 ms / 1000)


class TestValidateUrlEdgeCases:
    """_validate_url edge cases not covered elsewhere."""

    def test_hostless_url_raises(self) -> None:
        client = PageSpeedAPIClient()
        with pytest.raises(ValueError, match="hostname"):
            client._validate_url("http:///path-only")

    def test_empty_url_raises(self) -> None:
        client = PageSpeedAPIClient()
        with pytest.raises(ValueError, match="empty"):
            client._validate_url("")


# ---------------------------------------------------------------------------
# TD-3: API key must never leak into error messages
# ---------------------------------------------------------------------------

class TestApiKeyRedaction:
    """The key embedded in a connection-error URL must be redacted."""

    def test_connection_error_redacts_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        key = "SUPERSECRETKEY123"
        client = PageSpeedAPIClient(api_key=key, max_retries=1, retry_delay=0.0)

        def boom(url, **kwargs):
            raise requests.exceptions.ConnectionError(
                "HTTPSConnectionPool(host='www.googleapis.com', port=443): "
                f"Max retries exceeded with url: /pagespeedonline/v5/runPagespeed"
                f"?key={key}&url=https%3A%2F%2Fdemo.myshopify.com"
            )

        monkeypatch.setattr("integrations.pagespeed_api.requests.get", boom)

        with pytest.raises(RuntimeError, match=r"\*\*\*") as excinfo:
            client.get_metrics("https://demo.myshopify.com")
        assert key not in str(excinfo.value)

    def test_redact_message_covers_percent_encoded_key(self) -> None:
        client = PageSpeedAPIClient(api_key="SUPERSECRET KEY")
        msg = "url: /runPagespeed?key=SUPERSECRET%20KEY&url=https://demo"
        out = client._redact_message(msg)
        assert "SUPERSECRET" not in out
        assert "***" in out

    def test_redact_message_returns_text_when_no_key(self) -> None:
        client = PageSpeedAPIClient(api_key=None)
        assert client._redact_message("plain error") == "plain error"


# ---------------------------------------------------------------------------
# TD-3: PAGESPEED_API_KEY env var as --api-key fallback
# ---------------------------------------------------------------------------

class TestApiKeyEnvvar:
    """`PAGESPEED_API_KEY` supplies the key when --api-key is omitted."""

    @staticmethod
    def _sample_metrics(url: str) -> PageSpeedMetrics:
        return PageSpeedMetrics(
            lcp=2.5, cls=0.05, inp=0.1,
            first_contentful_paint=1.2, first_meaningful_paint=1.5,
            speed_index=1.8, time_to_interactive=3.5, total_blocking_time=150,
            performance_score=90, url=url, strategy="mobile",
            fetch_time="2026-01-01T00:00:00Z",
        )

    def _invoke_measure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        env_key: str | None,
        flag_key: str | None = None,
    ) -> dict:
        captured: dict = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs

            def get_metrics(self, url, strategy):
                return TestApiKeyEnvvar._sample_metrics(url)

        monkeypatch.setattr("engine.cli.PageSpeedAPIClient", FakeClient)
        if env_key is None:
            monkeypatch.delenv("PAGESPEED_API_KEY", raising=False)
        else:
            monkeypatch.setenv("PAGESPEED_API_KEY", env_key)

        args = ["measure", "https://demo.myshopify.com"]
        if flag_key is not None:
            args += ["--api-key", flag_key]
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, result.stdout
        assert "client_kwargs" in captured
        return captured

    def test_envvar_used_when_flag_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = self._invoke_measure(monkeypatch, env_key="env-secret")
        assert captured["client_kwargs"]["api_key"] == "env-secret"

    def test_flag_overrides_envvar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = self._invoke_measure(monkeypatch, env_key="env-secret", flag_key="flag-secret")
        assert captured["client_kwargs"]["api_key"] == "flag-secret"

    def test_no_key_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = self._invoke_measure(monkeypatch, env_key=None)
        assert captured["client_kwargs"]["api_key"] is None
