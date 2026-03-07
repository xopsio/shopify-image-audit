"""
Tests for the null-safe _extract_vitals function in audit_orchestrator.
Verifies that None values do not raise TypeError (bug #2 fix).
"""
from __future__ import annotations
import pytest
from engine.audit_orchestrator import _extract_vitals

class TestExtractVitals:
    def test_empty_data_returns_zeros(self) -> None:
        result = _extract_vitals({})
        assert result == {"lcp_ms": 0.0, "cls": 0.0, "inp_ms": 0.0, "ttfb_ms": 0.0}

    def test_none_values_do_not_raise(self) -> None:
        data = {"lcp_ms": None, "cls": None, "inp_ms": None, "ttfb_ms": None}
        result = _extract_vitals(data)
        assert result == {"lcp_ms": 0.0, "cls": 0.0, "inp_ms": 0.0, "ttfb_ms": 0.0}

    def test_fixture_top_level_vitals(self) -> None:
        data = {"lcp_ms": 2500.0, "cls": 0.1, "inp_ms": 200.0, "ttfb_ms": 400.0}
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 2500.0

    def test_lhr_metrics_audit_takes_precedence(self) -> None:
        data = {
            "lcp_ms": 9999.0,
            "audits": {
                "metrics": {
                    "details": {
                        "items": [{
                            "largestContentfulPaint": 1800,
                            "cumulativeLayoutShift": 0.05,
                            "interactive": 150,
                            "serverResponseTime": 300,
                        }]
                    }
                }
            },
        }
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 1800.0

    def test_lhr_none_metric_items_falls_back(self) -> None:
        data = {
            "lcp_ms": 1234.0,
            "audits": {"metrics": {"details": {"items": []}}}
        }
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 1234.0

    def test_lhr_null_metrics_audit(self) -> None:
        data = {"audits": {"metrics": None}, "lcp_ms": 500.0}
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 500.0

    def test_string_values_convert(self) -> None:
        data = {"lcp_ms": "1500", "cls": "0.2"}
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 1500.0

    def test_non_numeric_string_defaults_zero(self) -> None:
        data = {"lcp_ms": "not-a-number", "cls": "bad"}
        result = _extract_vitals(data)
        assert result["lcp_ms"] == 0.0

