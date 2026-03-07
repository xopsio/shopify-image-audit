"""
CLI behaviour tests covering the three Qodo blockers:

1. ``audit report`` writes an HTML file instead of no-op success.
2. ``audit run`` returns exit code 10 only for Lighthouse execution failures
   and exit code 2 for invalid input / JSON / validation errors.
3. ``audit extract`` and ``audit score`` catch invalid JSON / unexpected JSON
   types and exit cleanly with code 2.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from engine.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "fixtures"

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bad_json_file(tmp_path: Path, name: str = "bad.json") -> Path:
    p = tmp_path / name
    p.write_text("this is not valid json", encoding="utf-8")
    return p


def _non_object_json(tmp_path: Path, name: str = "list.json") -> Path:
    """A valid JSON file whose top-level value is a list, not an object."""
    p = tmp_path / name
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    return p


def _non_list_json(tmp_path: Path, name: str = "obj.json") -> Path:
    """A valid JSON file whose top-level value is an object, not a list."""
    p = tmp_path / name
    p.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# audit report – fix 1: must write HTML file
# ---------------------------------------------------------------------------

class TestReportWritesHtml:
    def test_report_creates_html_file(self, tmp_path: Path) -> None:
        """report must write an HTML file and exit 0."""
        result_json = tmp_path / "audit_result.json"
        result_json.write_text(
            json.dumps({
                "meta": {
                    "url": "https://example.myshopify.com",
                    "timestamp_utc": "2026-03-07T00:00:00Z",
                    "device": "mobile",
                    "runs": 1,
                    "tool": "lighthouse",
                },
                "vitals": {"lcp_ms": 1200.0, "cls": 0.05, "inp_ms": 100.0, "ttfb_ms": 200.0},
                "images": [
                    {
                        "src": "https://cdn.shopify.com/img.webp",
                        "role": "hero",
                        "score": 85,
                        "bytes": 95000,
                        "mime": "image/webp",
                        "is_lcp_candidate": True,
                        "recommendation": "OK",
                    }
                ],
                "summary": {"top_issues": ["All images look well optimised"]},
            }),
            encoding="utf-8",
        )
        out_html = tmp_path / "report.html"

        result = runner.invoke(app, ["report", str(result_json), "--output", str(out_html)])

        assert result.exit_code == 0, f"Unexpected exit code {result.exit_code}: {result.output}"
        assert out_html.exists(), "HTML output file was not created"
        content = out_html.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "example.myshopify.com" in content

    def test_report_html_contains_image_data(self, tmp_path: Path) -> None:
        result_json = tmp_path / "result.json"
        result_json.write_text(
            json.dumps({
                "meta": {
                    "url": "https://shop.example.com",
                    "timestamp_utc": "2026-03-07T12:00:00Z",
                    "device": "desktop",
                    "runs": 3,
                    "tool": "lighthouse",
                },
                "vitals": {"lcp_ms": 800.0, "cls": 0.01, "inp_ms": 50.0, "ttfb_ms": 100.0},
                "images": [
                    {
                        "src": "https://cdn.shopify.com/hero.webp",
                        "role": "hero",
                        "score": 90,
                        "bytes": 80000,
                        "mime": "image/webp",
                        "recommendation": "OK",
                    }
                ],
                "summary": {"top_issues": ["All images look well optimised"]},
            }),
            encoding="utf-8",
        )
        out_html = tmp_path / "out.html"
        result = runner.invoke(app, ["report", str(result_json), "--output", str(out_html)])

        assert result.exit_code == 0
        content = out_html.read_text(encoding="utf-8")
        assert "hero.webp" in content
        assert "hero" in content

    def test_report_missing_file_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["report", str(tmp_path / "nonexistent.json")])
        assert result.exit_code == 2

    def test_report_invalid_json_exits_2(self, tmp_path: Path) -> None:
        bad = _bad_json_file(tmp_path)
        result = runner.invoke(app, ["report", str(bad)])
        assert result.exit_code == 2

    def test_report_non_object_json_exits_2(self, tmp_path: Path) -> None:
        non_obj = _non_object_json(tmp_path)
        result = runner.invoke(app, ["report", str(non_obj)])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# audit run – fix 2: exit codes 10 vs 2
# ---------------------------------------------------------------------------

class TestRunExitCodes:
    def test_run_invalid_device_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            ["run", "https://example.com", "--device", "tablet", "--lhr", str(FIXTURES / "bad_hero_lcp.json")],
        )
        assert result.exit_code == 2

    def test_run_invalid_runs_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            ["run", "https://example.com", "--runs", "0", "--lhr", str(FIXTURES / "bad_hero_lcp.json")],
        )
        assert result.exit_code == 2

    def test_run_missing_lhr_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            ["run", "https://example.com", "--lhr", str(tmp_path / "nonexistent.json")],
        )
        assert result.exit_code == 2

    def test_run_invalid_json_lhr_exits_2(self, tmp_path: Path) -> None:
        bad = _bad_json_file(tmp_path)
        result = runner.invoke(
            app,
            ["run", "https://example.com", "--lhr", str(bad)],
        )
        assert result.exit_code == 2

    def test_run_valid_fixture_exits_0(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "run",
                "https://example.myshopify.com",
                "--device", "mobile",
                "--lhr", str(FIXTURES / "bad_hero_lcp.json"),
                "--out-dir", str(tmp_path / "artifacts"),
            ],
        )
        assert result.exit_code == 0
        assert (tmp_path / "artifacts" / "audit_result.json").exists()

    def test_run_writes_audit_result_json(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        runner.invoke(
            app,
            [
                "run",
                "https://example.myshopify.com",
                "--lhr", str(FIXTURES / "optimized_shopify.json"),
                "--out-dir", str(out),
            ],
        )
        assert (out / "audit_result.json").exists()


# ---------------------------------------------------------------------------
# audit extract – fix 3: invalid JSON / unexpected type → exit 2
# ---------------------------------------------------------------------------

class TestExtractExitCodes:
    def test_extract_valid_fixture_exits_0(self) -> None:
        result = runner.invoke(app, ["extract", str(FIXTURES / "bad_hero_lcp.json")])
        assert result.exit_code == 0

    def test_extract_missing_file_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["extract", str(tmp_path / "missing.json")])
        assert result.exit_code == 2

    def test_extract_invalid_json_exits_2(self, tmp_path: Path) -> None:
        bad = _bad_json_file(tmp_path)
        result = runner.invoke(app, ["extract", str(bad)])
        assert result.exit_code == 2

    def test_extract_non_object_json_exits_2(self, tmp_path: Path) -> None:
        non_obj = _non_object_json(tmp_path)
        result = runner.invoke(app, ["extract", str(non_obj)])
        assert result.exit_code == 2

    def test_extract_output_is_json_array(self) -> None:
        result = runner.invoke(app, ["extract", str(FIXTURES / "bad_hero_lcp.json")])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert len(parsed) > 0


# ---------------------------------------------------------------------------
# audit score – fix 3: invalid JSON / unexpected type → exit 2
# ---------------------------------------------------------------------------

class TestScoreExitCodes:
    def _extracted_file(self, tmp_path: Path) -> Path:
        """Helper: run extract, save output, return path."""
        result = runner.invoke(app, ["extract", str(FIXTURES / "bad_hero_lcp.json")])
        assert result.exit_code == 0
        extracted = tmp_path / "extracted.json"
        extracted.write_text(result.output, encoding="utf-8")
        return extracted

    def test_score_valid_input_exits_0(self, tmp_path: Path) -> None:
        extracted = self._extracted_file(tmp_path)
        result = runner.invoke(app, ["score", str(extracted)])
        assert result.exit_code == 0

    def test_score_missing_file_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["score", str(tmp_path / "missing.json")])
        assert result.exit_code == 2

    def test_score_invalid_json_exits_2(self, tmp_path: Path) -> None:
        bad = _bad_json_file(tmp_path)
        result = runner.invoke(app, ["score", str(bad)])
        assert result.exit_code == 2

    def test_score_non_list_json_exits_2(self, tmp_path: Path) -> None:
        non_list = _non_list_json(tmp_path)
        result = runner.invoke(app, ["score", str(non_list)])
        assert result.exit_code == 2

    def test_score_output_has_role_and_score(self, tmp_path: Path) -> None:
        extracted = self._extracted_file(tmp_path)
        result = runner.invoke(app, ["score", str(extracted)])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        for img in parsed:
            assert "role" in img
            assert "score" in img
            assert 0 <= img["score"] <= 100
