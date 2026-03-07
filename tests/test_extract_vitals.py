"""
Tests for the null-safe _extract_vitals function in audit_orchestrator.
Verifies that None values do not raise TypeError (bug #2 fix).
"""

from __future__ import annotations

import pytest

from engine.audit_orchestrator import _extract_vitals


class TestExtractVitals:
    """Tests for null-safe _extract_vitals."""

    def test_empty_data_returns_zeros(self) -> None:
        """Empty dict → all vitals default to 0.0."""
        result = _extract_vitals({})
        assert result == {"lcp_ms": 0.0, "cls": 0.0, "inp_ms": 0.0, "ttfb_ms": 0.0}

    def test_none_values_do_not_raise(self) -> None:
        """Explicit None values for vitals should default to 0.0, not raise TypeError."""
        data = {"lcp_ms": None, "cls": None, "inp_ms": None, "ttfb_ms": None}
        result = _extract_vitals(data)
        assert result == {"lcp_ms": 0.0, "cls": 0.0, "inp_ms": 0.0, "ttfb_ms": 0.0}

    def test_fixture_top_level_vitals(self) -> None:
        """Fixture-style JSON with top-level vitals fields."""
        data = {"lcp_ms": 2500.0, "cls": 0.1, "inp_ms": 200.0, "ttfb_ms": 400.0}
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 2500.0
        assert result["cls"] == 0.1
        assert result["inp_ms"] == 200.0
        assert result["ttfb_ms"] == 400.0

    def test_lhr_metrics_audit_takes_precedence(self) -> None:
        """LHR metrics.details.items[0] values take precedence over top-level vitals."""
        data = {
            "lcp_ms": 9999.0,
            "audits": {
                "metrics": {
                    "details": {
                        "items": [
                            {
                                "largestContentfulPaint": 1800,
                                "cumulativeLayoutShift": 0.05,
                                "interactive": 150,
                                "serverResponseTime": 300,
                            }
                        ]
                    }
                }
            },
        }
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 1800.0
        assert result["cls"] == 0.05
        assert result["inp_ms"] == 150.0
        assert result["ttfb_ms"] == 300.0

    def test_lhr_none_metric_items_falls_back_to_top_level(self) -> None:
        """If LHR metrics items is empty/None, falls back to top-level vitals."""
        data = {
            "lcp_ms": 1234.0,
            "audits": {
                "metrics": {
                    "details": {
                        "items": []
                    }
                }
            },
        }
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 1234.0

    def test_lhr_null_metrics_audit(self) -> None:
        """audits.metrics being None/missing should not raise."""
        data = {"audits": {"metrics": None}, "lcp_ms": 500.0}
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 500.0

    def test_string_values_convert_to_float(self) -> None:
        """String numeric values should be coerced to float."""
        data = {"lcp_ms": "1500", "cls": "0.2", "inp_ms": "100", "ttfb_ms": "250"}
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 1500.0
        assert result["cls"] == 0.2

    def test_non_numeric_string_defaults_to_zero(self) -> None:
        """Non-numeric string values should default to 0.0 without raising."""
        data = {"lcp_ms": "not-a-number", "cls": "bad"}
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 0.0
        assert result["cls"] == 0.0
