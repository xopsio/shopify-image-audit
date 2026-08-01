"""
CLI coverage close-out (Sprint 5, TD-2).

Fills the gaps in CLI test coverage: commands that previously had no happy-path
test in the Typer runner. Adds integration tests for:

- ``audit version``
- ``audit measure`` (with mocked PageSpeed API)
- ``audit extract`` (happy path with fixture)
- ``audit score`` (happy path with both rankers)
- ``audit history list`` / ``audit history show`` (with ``--history-dir`` override)
- ``audit history`` unknown subcommand
- ``audit baseline`` records to history (extends existing TestBaselineCommand)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses
from typer.testing import CliRunner

from engine.cli import app
from tests import FIXTURES

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_audit() -> dict:
    return {
        "meta": {
            "url": "https://demo.myshopify.com",
            "timestamp_utc": "2026-07-30T15:00:00Z",
            "device": "mobile",
            "runs": 1,
            "tool": "lighthouse",
        },
        "vitals": {"lcp_ms": 1500.0, "cls": 0.05, "inp_ms": 100.0, "ttfb_ms": 400.0},
        "images": [
            {
                "src": "https://cdn.example.com/hero.jpg",
                "role": "hero",
                "score": 80,
                "bytes": 100_000,
                "mime": "image/jpeg",
            },
        ],
        "summary": {"top_issues": []},
    }


# ---------------------------------------------------------------------------
# audit version
# ---------------------------------------------------------------------------


class TestVersionCommand:
    def test_version_prints_package_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        # Should print the version (0.3.0 or later)
        out = result.stdout
        assert "shopify-image-audit" in out
        # Version is a dotted string
        import re

        assert re.search(r"\d+\.\d+\.\d+", out), f"No version found in: {out!r}"

    def test_get_version_helper_returns_string(self) -> None:
        from engine.cli import _get_version

        version = _get_version()
        assert isinstance(version, str)
        assert version != "unknown"  # Should read from pyproject.toml


# ---------------------------------------------------------------------------
# audit measure
# ---------------------------------------------------------------------------


class TestMeasureCommand:
    """Mock PageSpeed API responses to test the CLI integration."""

    @responses.activate
    def test_measure_happy_path_stdout(self) -> None:
        responses.add(
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
                    "configSettings": {"formFactor": "mobile"},
                    "finalUrl": "https://demo.myshopify.com",
                    "fetchTime": "2026-07-30T15:00:00Z",
                }
            },
            status=200,
        )
        result = runner.invoke(app, ["measure", "https://demo.myshopify.com", "--no-cache"])
        assert result.exit_code == 0
        # Stdout should contain the metrics JSON
        assert "lcp" in result.stdout.lower() or "1800" in result.stdout

    @responses.activate
    def test_measure_writes_output_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        responses.add(
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
                    "configSettings": {"formFactor": "mobile"},
                    "finalUrl": "https://demo.myshopify.com",
                    "fetchTime": "2026-07-30T15:00:00Z",
                }
            },
            status=200,
        )
        output = tmp_path / "metrics.json"
        # validate_out_path requires a relative path; chdir then use basename.
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            ["measure", "https://demo.myshopify.com", "-o", "metrics.json", "--no-cache"],
        )
        assert result.exit_code == 0, f"Output: {result.stdout}"
        assert output.exists()
        payload = json.loads(output.read_text())
        assert "lcp_ms" in payload or "lcp" in str(payload).lower()

    def test_measure_invalid_strategy_exits_2(self) -> None:
        result = runner.invoke(app, ["measure", "https://demo.myshopify.com", "--strategy", "tablet", "--no-cache"])
        assert result.exit_code == 2
        assert "strategy" in result.stdout.lower() or "invalid" in result.stdout.lower()


# ---------------------------------------------------------------------------
# audit extract
# ---------------------------------------------------------------------------


class TestExtractCommand:
    def test_extract_happy_path(self, tmp_path: Path) -> None:
        """extract should output parsed image data from a Lighthouse JSON fixture."""
        fixture = FIXTURES / "bad_hero_lcp.json"
        result = runner.invoke(app, ["extract", str(fixture)])
        assert result.exit_code == 0
        # Output is JSON list of image dicts
        payload = json.loads(result.stdout)
        assert isinstance(payload, list)
        assert len(payload) >= 1
        # Each item should have the standard parsed-image keys
        first = payload[0]
        assert "src" in first

    def test_extract_missing_file_exits_2(self) -> None:
        result = runner.invoke(app, ["extract", "/nonexistent/lighthouse.json"])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# audit score
# ---------------------------------------------------------------------------


class TestScoreCommand:
    def test_score_heuristic_happy_path(self, tmp_path: Path) -> None:
        """score with default --ranker heuristic should succeed on a parsed-image list."""
        # Create a parsed-images JSON
        input_path = tmp_path / "extracted.json"
        input_path.write_text(
            json.dumps(
                [
                    {
                        "src": "https://cdn.example.com/hero.jpg",
                        "resourceSize": 120000,
                        "mimeType": "image/jpeg",
                        "displayedWidth": 1200,
                        "displayedHeight": 600,
                        "naturalWidth": 2400,
                        "naturalHeight": 1200,
                    },
                ]
            )
        )
        result = runner.invoke(app, ["score", str(input_path)])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert isinstance(payload, list)
        # Each scored image must have role + score + recommendation
        assert "role" in payload[0]
        assert "score" in payload[0]
        assert "recommendation" in payload[0]

    def test_score_ml_ranker_branch(self, tmp_path: Path) -> None:
        """--ranker ml should select the ML-style ensemble ranker."""
        input_path = tmp_path / "extracted.json"
        input_path.write_text(
            json.dumps(
                [
                    {
                        "src": "https://cdn.example.com/hero.jpg",
                        "resourceSize": 120000,
                        "mimeType": "image/jpeg",
                        "displayedWidth": 1200,
                        "displayedHeight": 600,
                        "naturalWidth": 2400,
                        "naturalHeight": 1200,
                    },
                ]
            )
        )
        result = runner.invoke(app, ["score", str(input_path), "--ranker", "ml"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert isinstance(payload, list)

    def test_score_invalid_ranker_exits_2(self, tmp_path: Path) -> None:
        input_path = tmp_path / "extracted.json"
        input_path.write_text(json.dumps([]))
        result = runner.invoke(app, ["score", str(input_path), "--ranker", "bogus"])
        assert result.exit_code == 2

    def test_score_missing_file_exits_2(self) -> None:
        result = runner.invoke(app, ["score", "/nonexistent/extracted.json"])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# audit history
# ---------------------------------------------------------------------------


class TestHistoryCliDispatcher:
    """The `audit history` subcommand: list, show, diff (later), and unknown."""

    def test_unknown_history_subcommand_exits_2(self) -> None:
        result = runner.invoke(app, ["history", "delete", "mystore.myshopify.com"])
        assert result.exit_code == 2
        assert "unknown" in result.stdout.lower() or "subcommand" in result.stdout.lower()

    def test_history_list_empty_exits_0(self, tmp_path: Path) -> None:
        """An empty history directory is not an error — exit 0 with a friendly message."""
        result = runner.invoke(
            app,
            [
                "history",
                "list",
                "mystore.myshopify.com",
                "--history-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        assert "no history" in result.stdout.lower() or "no entries" in result.stdout.lower()

    def test_history_show_empty_exits_0(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "history",
                "show",
                "mystore.myshopify.com",
                "--history-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        assert "no history" in result.stdout.lower() or "no entries" in result.stdout.lower()

    def test_history_list_with_entries(self, tmp_path: Path) -> None:
        """Record a baseline first, then list."""
        # Use a real LHR fixture and a custom history dir
        fixture = FIXTURES / "bad_hero_lcp.json"
        result = runner.invoke(
            app,
            [
                "baseline",
                str(fixture),
                "--save",
                "baseline.json",
                "--history-dir",
                str(tmp_path / "history"),
            ],
        )
        assert result.exit_code == 0

        # Now list (the bad_hero_lcp fixture has URL cdn.shopify.com — that's the hostname)
        result = runner.invoke(
            app,
            [
                "history",
                "list",
                "cdn.shopify.com",
                "--history-dir",
                str(tmp_path / "history"),
            ],
        )
        assert result.exit_code == 0

    def test_history_show_with_entries(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Record a baseline first, then generate a trend HTML."""
        fixture = FIXTURES / "bad_hero_lcp.json"
        result = runner.invoke(
            app,
            [
                "baseline",
                str(fixture),
                "--save",
                "baseline.json",
                "--history-dir",
                str(tmp_path / "history"),
            ],
        )
        assert result.exit_code == 0

        # validate_out_path requires relative; chdir then pass basename.
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "history",
                "show",
                "cdn.shopify.com",
                "--history-dir",
                str(tmp_path / "history"),
                "-o",
                "trend.html",
            ],
        )
        assert result.exit_code == 0, f"Output: {result.stdout}"
        out_html = tmp_path / "trend.html"
        assert out_html.exists()
        assert "Audit History" in out_html.read_text()


# ---------------------------------------------------------------------------
# audit baseline records to history (extends existing coverage)
# ---------------------------------------------------------------------------


class TestBaselineRecordsHistory:
    """The baseline command must record a snapshot to HistoryStore."""

    def test_baseline_writes_to_history_dir(self, tmp_path: Path) -> None:
        fixture = FIXTURES / "bad_hero_lcp.json"
        history_dir = tmp_path / "history"
        result = runner.invoke(
            app,
            [
                "baseline",
                str(fixture),
                "--save",
                "baseline.json",
                "--history-dir",
                str(history_dir),
                "--label",
                "Initial baseline",
            ],
        )
        assert result.exit_code == 0
        # A hostname directory must exist with at least one .json file
        host_dirs = [d for d in history_dir.iterdir() if d.is_dir()]
        assert len(host_dirs) == 1
        snapshot_files = list(host_dirs[0].glob("*.json"))
        assert len(snapshot_files) == 1
        # Snapshot should have the label
        snapshot = json.loads(snapshot_files[0].read_text())
        assert snapshot["_history_label"] == "Initial baseline"
