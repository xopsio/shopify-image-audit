"""
Targeted unit tests for _extract_vitals and safe_float in audit_orchestrator.

Covers:
- empty dict → all zeros
- explicit None values
- top-level fixture vitals (fallback keys)
- LHR metrics precedence over top-level keys
- empty metrics items list → fallback to top-level
- null metrics audit → fallback to top-level
- string numeric conversion
- non-numeric strings → zero
"""

from __future__ import annotations

import pytest

from engine.audit_orchestrator import _extract_vitals, safe_float


# ---------------------------------------------------------------------------
# safe_float unit tests
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_none_returns_default(self) -> None:
        assert safe_float(None) == 0.0

    def test_none_returns_custom_default(self) -> None:
        assert safe_float(None, default=99.9) == 99.9

    def test_numeric_string_converts(self) -> None:
        assert safe_float("3.14") == pytest.approx(3.14)

    def test_non_numeric_string_returns_default(self) -> None:
        assert safe_float("not-a-number") == 0.0

    def test_integer_converts(self) -> None:
        assert safe_float(1200) == pytest.approx(1200.0)

    def test_float_passthrough(self) -> None:
        assert safe_float(2.5) == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# _extract_vitals unit tests
# ---------------------------------------------------------------------------

class TestExtractVitals:
    def test_empty_dict_all_zeros(self) -> None:
        """Empty input → all four fields default to 0.0."""
        result = _extract_vitals({})
        assert result == {"lcp_ms": 0.0, "cls": 0.0, "inp_ms": 0.0, "ttfb_ms": 0.0}

    def test_explicit_none_values_at_top_level(self) -> None:
        """Top-level keys set to None → all four fields default to 0.0."""
        result = _extract_vitals({"lcp_ms": None, "cls": None, "inp_ms": None, "ttfb_ms": None})
        assert result == {"lcp_ms": 0.0, "cls": 0.0, "inp_ms": 0.0, "ttfb_ms": 0.0}

    def test_top_level_fixture_vitals(self) -> None:
        """Top-level vitals keys (fixture format) are used when no LHR audits present."""
        data = {"lcp_ms": 1500.0, "cls": 0.1, "inp_ms": 200.0, "ttfb_ms": 400.0}
        result = _extract_vitals(data)
        assert result["lcp_ms"] == pytest.approx(1500.0)
        assert result["cls"] == pytest.approx(0.1)
        assert result["inp_ms"] == pytest.approx(200.0)
        assert result["ttfb_ms"] == pytest.approx(400.0)

    def test_lhr_metrics_take_precedence_over_top_level(self) -> None:
        """LHR audits.metrics values override top-level fallback keys."""
        data = {
            "lcp_ms": 9999.0,  # should be ignored
            "audits": {
                "metrics": {
                    "details": {
                        "items": [{
                            "largestContentfulPaint": 1200,
                            "cumulativeLayoutShift": 0.05,
                            "interactive": 150,
                            "serverResponseTime": 300,
                        }]
                    }
                }
            },
        }
        result = _extract_vitals(data)
        assert result["lcp_ms"] == pytest.approx(1200.0)
        assert result["cls"] == pytest.approx(0.05)
        assert result["inp_ms"] == pytest.approx(150.0)
        assert result["ttfb_ms"] == pytest.approx(300.0)

    def test_empty_metrics_items_falls_back_to_top_level(self) -> None:
        """audits.metrics.details.items = [] → fall back to top-level vitals."""
        data = {
            "lcp_ms": 800.0,
            "audits": {"metrics": {"details": {"items": []}}},
        }
        result = _extract_vitals(data)
        assert result["lcp_ms"] == pytest.approx(800.0)

    def test_null_metrics_audit_falls_back_to_top_level(self) -> None:
        """audits.metrics = None → fall back to top-level vitals without error."""
        data = {
            "lcp_ms": 700.0,
            "audits": {"metrics": None},
        }
        result = _extract_vitals(data)
        assert result["lcp_ms"] == pytest.approx(700.0)

    def test_string_numeric_values_convert(self) -> None:
        """String-encoded numbers in LHR items are converted correctly."""
        data = {
            "audits": {
                "metrics": {
                    "details": {
                        "items": [{
                            "largestContentfulPaint": "2500",
                            "cumulativeLayoutShift": "0.02",
                            "interactive": "350",
                            "serverResponseTime": "120",
                        }]
                    }
                }
            }
        }
        result = _extract_vitals(data)
        assert result["lcp_ms"] == pytest.approx(2500.0)
        assert result["cls"] == pytest.approx(0.02)
        assert result["inp_ms"] == pytest.approx(350.0)
        assert result["ttfb_ms"] == pytest.approx(120.0)

    def test_non_numeric_strings_return_zero(self) -> None:
        """Non-numeric strings in LHR items → 0.0 (no crash)."""
        data = {
            "audits": {
                "metrics": {
                    "details": {
                        "items": [{
                            "largestContentfulPaint": "n/a",
                            "cumulativeLayoutShift": "pending",
                            "interactive": "unknown",
                            "serverResponseTime": "error",
                        }]
                    }
                }
            }
        }
        result = _extract_vitals(data)
        assert result == {"lcp_ms": 0.0, "cls": 0.0, "inp_ms": 0.0, "ttfb_ms": 0.0}
