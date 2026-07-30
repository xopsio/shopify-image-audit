"""
Tests for CLI input safety guards (URL scheme, --out-dir validation).
Verifies that invalid inputs produce exit code 2.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses
from typer.testing import CliRunner

from engine.cli import app

runner = CliRunner()


class TestCliUrlScheme:
    def test_file_scheme_rejected(self) -> None:
        result = runner.invoke(app, ["run", "file:///etc/passwd"])
        assert result.exit_code == 2

    def test_chrome_scheme_rejected(self) -> None:
        result = runner.invoke(app, ["run", "chrome://settings"])
        assert result.exit_code == 2

    def test_no_scheme_rejected(self) -> None:
        result = runner.invoke(app, ["run", "example.com"])
        assert result.exit_code == 2


class TestCliOutDir:
    def test_absolute_path_rejected(self) -> None:
        result = runner.invoke(app, ["run", "https://example.com", "--out-dir", "C:\\absolute\\path"])
        assert result.exit_code == 2

    def test_dotdot_rejected(self) -> None:
        result = runner.invoke(app, ["run", "https://example.com", "--out-dir", "foo/../../../etc"])
        assert result.exit_code == 2

    def test_valid_relative_outdir_passes_url_check(self) -> None:
        result = runner.invoke(app, ["run", "https://example.com", "--out-dir", "output"])
        # Should pass URL and out-dir checks; will fail later (no lighthouse),
        # but exit code should NOT be 2
        assert result.exit_code != 2


class TestReportCommand:
    """Test the report command."""

    def test_report_missing_file(self, tmp_path):
        """report should exit with code 2 if input file doesn't exist."""
        from typer.testing import CliRunner

        from engine.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["report", "nonexistent.json"])
        assert result.exit_code == 2
        assert "not found" in result.stdout.lower()

    def test_report_invalid_json(self, tmp_path):
        """report should exit with code 2 if input is not valid JSON."""
        from typer.testing import CliRunner

        from engine.cli import app

        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{invalid json}")

        runner = CliRunner()
        result = runner.invoke(app, ["report", str(bad_json)])
        assert result.exit_code == 2
        assert "invalid json" in result.stdout.lower()

    def test_report_success(self, tmp_path):
        """report should generate HTML successfully with valid input."""
        import json

        from typer.testing import CliRunner

        from engine.cli import app

        # Create a valid audit_result.json
        audit_result = {
            "meta": {
                "url": "https://example.com",
                "timestamp_utc": "2024-01-01T00:00:00Z",
                "device": "mobile",
                "runs": 3,
                "tool": "lighthouse",
            },
            "vitals": {
                "lcp_ms": 2000.0,
                "cls": 0.05,
                "inp_ms": 150.0,
                "ttfb_ms": 600.0,
            },
            "images": [
                {
                    "src": "test.jpg",
                    "role": "hero",
                    "score": 85,
                    "bytes": 50000,
                    "mime": "image/jpeg",
                    "displayed_width": 800,
                    "displayed_height": 600,
                }
            ],
            "summary": {"top_issues": ["Test issue"]},
        }

        input_file = tmp_path / "audit_result.json"
        input_file.write_text(json.dumps(audit_result))

        output_file = tmp_path / "report.html"

        runner = CliRunner()
        result = runner.invoke(app, ["report", str(input_file), "-o", str(output_file)])

        assert result.exit_code == 0
        assert output_file.exists()

        # Verify HTML contains expected content
        html_content = output_file.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html_content
        assert "Shopify Image Audit Report" in html_content
        assert "https://example.com" in html_content
        assert "test.jpg" in html_content


class TestExtractCommand:
    """Test the extract command error handling."""

    def test_extract_invalid_json(self, tmp_path):
        """extract should exit with code 2 if input is not valid JSON."""
        from typer.testing import CliRunner

        from engine.cli import app

        bad_json = tmp_path / "bad_lh.json"
        bad_json.write_text("{not valid json}")

        runner = CliRunner()
        result = runner.invoke(app, ["extract", str(bad_json)])
        assert result.exit_code == 2
        assert "invalid json" in result.stdout.lower()


class TestScoreCommand:
    """Test the score command error handling."""

    def test_score_invalid_json(self, tmp_path):
        """score should exit with code 2 if input is not valid JSON."""
        from typer.testing import CliRunner

        from engine.cli import app

        bad_json = tmp_path / "bad_audit.json"
        bad_json.write_text("{not valid json}")

        runner = CliRunner()
        result = runner.invoke(app, ["score", str(bad_json)])
        assert result.exit_code == 2
        assert "invalid json" in result.stdout.lower()


class TestOutDirSecurity:
    """Test --out-dir path traversal prevention."""

    def test_prefix_bypass_rejected(self):
        """Reject paths that look like prefix but escape containment."""
        from typer.testing import CliRunner

        from engine.cli import app

        runner = CliRunner()

        # This should be rejected even though string starts with cwd
        # Example: if cwd is /app, reject /app-attacker
        result = runner.invoke(app, ["run", "https://example.com", "--out-dir", "../sibling"])
        assert result.exit_code == 2
        assert "outside" in result.stdout.lower() or ".." in result.stdout.lower()


class TestReportSecurity:
    """Test HTML report XSS prevention."""

    def test_report_escapes_xss_in_url(self, tmp_path):
        """HTML report must escape XSS payloads in URL field."""
        import json

        from typer.testing import CliRunner

        from engine.cli import app

        # Malicious audit_result with XSS payload
        audit_result = {
            "meta": {
                "url": "<script>alert('XSS')</script>",
                "timestamp_utc": "2024-01-01T00:00:00Z",
                "device": "mobile",
                "runs": 3,
                "tool": "lighthouse",
            },
            "vitals": {
                "lcp_ms": 2000.0,
                "cls": 0.05,
                "inp_ms": 150.0,
                "ttfb_ms": 600.0,
            },
            "images": [
                {
                    "src": "<img src=x onerror=alert(1)>",
                    "role": "hero",
                    "score": 85,
                    "bytes": 50000,
                    "mime": "image/jpeg",
                    "recommendation": "<script>alert(2)</script>",
                }
            ],
            "summary": {"top_issues": ["<script>alert(3)</script>"]},
        }

        input_file = tmp_path / "malicious.json"
        input_file.write_text(json.dumps(audit_result))

        output_file = tmp_path / "report.html"

        runner = CliRunner()
        result = runner.invoke(app, ["report", str(input_file), "-o", str(output_file)])

        assert result.exit_code == 0
        assert output_file.exists()

        html_content = output_file.read_text(encoding="utf-8")

        # Verify XSS payloads are escaped, not executed
        assert "<script>" not in html_content
        assert "&lt;script&gt;" in html_content
        # The onerror payload should be inside escaped < > so it's not a real attribute
        assert "&lt;img src=x onerror=alert(1)&gt;" in html_content

        # Verify legitimate content still present (escaped)
        assert "alert" in html_content  # The word "alert" should still appear (escaped)


class TestBaselineCommand:
    """Test the `audit baseline` command."""

    def test_baseline_success(self, tmp_path, monkeypatch):
        """baseline should save a valid AuditResult JSON."""
        from typer.testing import CliRunner

        from engine.cli import app

        # Copy fixture into tmp_path so --save can use a relative path within cwd.
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, [
            "baseline", "baseline_lcp.json", "--save", "out/baseline.json",
        ])

        # Create the fixture in the cwd.
        (tmp_path / "baseline_lcp.json").write_text(json.dumps({
            "lcp_ms": 4000, "cls": 0.1, "inp_ms": 300, "ttfb_ms": 800,
            "images": [{"url": "hero.jpg", "resourceSize": 500000,
                        "mimeType": "image/jpeg", "displayedWidth": 800, "displayedHeight": 600}],
        }))
        result = runner.invoke(app, [
            "baseline", "baseline_lcp.json", "--save", "out/baseline.json",
        ])
        assert result.exit_code == 0, result.stdout
        assert (tmp_path / "out" / "baseline.json").exists()
        # Saved file must be a valid AuditResult
        saved = json.loads((tmp_path / "out" / "baseline.json").read_text())
        assert saved["vitals"]["lcp_ms"] == 4000

    def test_baseline_missing_file(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from engine.cli import app
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["baseline", "nope.json", "--save", "out.json"])
        assert result.exit_code == 2

    def test_baseline_rejects_absolute_save_path(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from engine.cli import app
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["baseline", "x.json", "--save", "/tmp/x.json"])
        assert result.exit_code == 2

    def test_baseline_invalid_device(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from engine.cli import app
        monkeypatch.chdir(tmp_path)
        (tmp_path / "f.json").write_text(json.dumps({"images": []}))
        runner = CliRunner()
        result = runner.invoke(app, ["baseline", "f.json", "--save", "out.json", "--device", "tablet"])
        assert result.exit_code == 2


class TestCompareCommand:
    """Test the `audit compare` command (before/after)."""

    @pytest.fixture
    def before_after_files(self, tmp_path, monkeypatch):
        """Create before/after fixtures in cwd and return their relative paths."""
        monkeypatch.chdir(tmp_path)
        before = {
            "lcp_ms": 4200, "cls": 0.18, "inp_ms": 320, "ttfb_ms": 900,
            "images": [{"url": "hero.jpg", "resourceSize": 1200000, "mimeType": "image/jpeg",
                        "displayedWidth": 1200, "displayedHeight": 600}],
        }
        after = {
            "lcp_ms": 1800, "cls": 0.04, "inp_ms": 180, "ttfb_ms": 620,
            "images": [{"url": "hero.webp", "resourceSize": 95000, "mimeType": "image/webp",
                        "displayedWidth": 1200, "displayedHeight": 600}],
        }
        (tmp_path / "before.json").write_text(json.dumps(before))
        (tmp_path / "after.json").write_text(json.dumps(after))
        return "before.json", "after.json"

    def test_compare_success_stdout_json(self, before_after_files):
        from typer.testing import CliRunner

        from engine.cli import app
        before, after = before_after_files
        runner = CliRunner()
        result = runner.invoke(app, ["compare", before, after])
        assert result.exit_code == 0, result.stdout
        # JSON comparison payload printed to stdout
        assert "vitals" in result.stdout
        assert "improved" in result.stdout

    def test_compare_writes_html_report(self, before_after_files):
        from typer.testing import CliRunner

        from engine.cli import app
        before, after = before_after_files
        runner = CliRunner()
        result = runner.invoke(app, ["compare", before, after, "-o", "report.html"])
        assert result.exit_code == 0, result.stdout
        html = Path("report.html").read_text(encoding="utf-8")
        assert "Before / After Comparison" in html
        assert "ROI estimate" in html

    def test_compare_writes_json_too(self, before_after_files):
        from typer.testing import CliRunner

        from engine.cli import app
        before, after = before_after_files
        runner = CliRunner()
        result = runner.invoke(app, ["compare", before, after, "--json", "cmp.json"])
        assert result.exit_code == 0, result.stdout
        cmp = json.loads(Path("cmp.json").read_text())
        assert cmp["vitals"]["lcp"]["status"] == "improved"

    def test_compare_missing_file(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from engine.cli import app
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["compare", "nope1.json", "nope2.json"])
        assert result.exit_code == 2
        assert "not found" in result.stdout.lower()

    def test_compare_rejects_absolute_output(self, before_after_files):
        from typer.testing import CliRunner

        from engine.cli import app
        before, after = before_after_files
        runner = CliRunner()
        result = runner.invoke(app, ["compare", before, after, "-o", "/tmp/x.html"])
        assert result.exit_code == 2

    def test_compare_works_with_saved_baseline(self, tmp_path, monkeypatch):
        """End-to-end: baseline then compare using the saved AuditResult file."""
        from typer.testing import CliRunner

        from engine.cli import app
        monkeypatch.chdir(tmp_path)
        raw = {
            "lcp_ms": 4200, "cls": 0.18, "inp_ms": 320, "ttfb_ms": 900,
            "images": [{"url": "hero.jpg", "resourceSize": 1200000, "mimeType": "image/jpeg",
                        "displayedWidth": 1200, "displayedHeight": 600}],
        }
        (tmp_path / "raw.json").write_text(json.dumps(raw))
        after = {
            "lcp_ms": 1800, "cls": 0.04, "inp_ms": 180, "ttfb_ms": 620,
            "images": [{"url": "hero.webp", "resourceSize": 95000, "mimeType": "image/webp",
                        "displayedWidth": 1200, "displayedHeight": 600}],
        }
        (tmp_path / "after.json").write_text(json.dumps(after))

        runner = CliRunner()
        # 1. save a baseline
        r1 = runner.invoke(app, ["baseline", "raw.json", "--save", "base.json"])
        assert r1.exit_code == 0
        # 2. compare saved baseline against raw after fixture
        r2 = runner.invoke(app, ["compare", "base.json", "after.json"])
        assert r2.exit_code == 0, r2.stdout
        assert "improved" in r2.stdout


class TestCompareWithLiveURL:
    """Test that `audit compare <baseline> <live URL>` fetches via PageSpeed API."""

    @staticmethod
    def _mock_pagespeed_response() -> dict:
        """A minimal Lighthouse-JSON-shaped response that the audit pipeline accepts."""
        return {
            "lighthouseResult": {
                "fetchTime": "2024-01-15T10:30:00.000Z",
                "requestedUrl": "https://demo.myshopify.com",
                "audits": {
                    "largest-contentful-paint": {"numericValue": 1800},
                    "cumulative-layout-shift": {"numericValue": 0.04},
                    "interactive": {"numericValue": 3500},
                    "server-response-time": {"numericValue": 800},
                    "metrics": {
                        "details": {
                            "items": [
                                {
                                    "largestContentfulPaint": 1800.0,
                                    "cumulativeLayoutShift": 0.04,
                                    "interactive": 3500.0,
                                    "serverResponseTime": 800.0,
                                },
                            ]
                        }
                    },
                },
                "categories": {"performance": {"score": 0.85}},
                # LHR-shaped image-elements audit (so the parser finds images)
                "image-elements": {
                    "details": {
                        "items": [
                            {
                                "url": "https://demo.myshopify.com/hero.webp",
                                "resourceSize": 95000,
                                "mimeType": "image/webp",
                                "displayedWidth": 1200,
                                "displayedHeight": 600,
                                "naturalWidth": 1200,
                                "naturalHeight": 600,
                            },
                        ]
                    }
                },
                "largest-contentful-paint-element": {
                    "details": {"items": [{"url": "https://demo.myshopify.com/hero.webp"}]}
                },
            }
        }

    @responses.activate
    def test_compare_against_live_url(self, tmp_path, monkeypatch):
        """Baseline (file) vs current (URL) — full CLI smoke with mocked PSI."""
        from typer.testing import CliRunner

        from engine.cli import app

        monkeypatch.chdir(tmp_path)

        # Saved baseline (good state) — build via the pipeline so it's
        # schema-compliant.
        before_json = {
            "lcp_ms": 4200, "cls": 0.18, "inp_ms": 320, "ttfb_ms": 900,
            "images": [{"url": "hero.jpg", "resourceSize": 1_200_000,
                        "mimeType": "image/jpeg",
                        "displayedWidth": 1200, "displayedHeight": 600,
                        "is_lcp_candidate": True}],
        }
        (tmp_path / "before.json").write_text(json.dumps(before_json))

        # Mock PageSpeed API to return the LHR above.
        responses.add(
            responses.GET,
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            json=self._mock_pagespeed_response(),
            status=200,
        )

        runner = CliRunner()
        result = runner.invoke(app, [
            "compare", "before.json", "https://demo.myshopify.com",
            "--strategy", "mobile",
        ])
        # Exit code 0 = success (a happy-path LCP improvement is expected).
        assert result.exit_code == 0, result.stdout
        # The "improved" word appears in the comparison table for LCP delta.
        assert "improved" in result.stdout
        # And we actually called PageSpeed (responses-mock matches by URL).
        assert len(responses.calls) == 1

    @responses.activate
    def test_compare_live_url_with_html_output(self, tmp_path, monkeypatch):
        """Live URL + HTML output must render the comparison section."""
        from typer.testing import CliRunner

        from engine.cli import app

        monkeypatch.chdir(tmp_path)
        before_json = {
            "lcp_ms": 4200, "cls": 0.18, "inp_ms": 320, "ttfb_ms": 900,
            "images": [],
        }
        (tmp_path / "before.json").write_text(json.dumps(before_json))
        responses.add(
            responses.GET,
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            json=self._mock_pagespeed_response(),
            status=200,
        )

        runner = CliRunner()
        result = runner.invoke(app, [
            "compare", "before.json", "https://demo.myshopify.com",
            "-o", "report.html",
        ])
        assert result.exit_code == 0, result.stdout
        html = Path("report.html").read_text(encoding="utf-8")
        assert "Before / After Comparison" in html

    @responses.activate
    def test_compare_live_url_api_error(self, tmp_path, monkeypatch):
        """API failure -> exit 10 (backend/Lighthouse/API failure convention)."""
        from typer.testing import CliRunner

        from engine.cli import app

        monkeypatch.chdir(tmp_path)
        before_json = {
            "lcp_ms": 4200, "cls": 0.18, "inp_ms": 320, "ttfb_ms": 900,
            "images": [],
        }
        (tmp_path / "before.json").write_text(json.dumps(before_json))

        # All retries fail with 500 — the client raises RuntimeError after
        # retries are exhausted.
        responses.add(
            responses.GET,
            "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
            status=500,
            body="Internal Server Error",
        )

        runner = CliRunner()
        result = runner.invoke(app, [
            "compare", "before.json", "https://demo.myshopify.com",
        ])
        assert result.exit_code == 10
        assert "PageSpeed API" in result.stdout

    def test_compare_live_url_invalid_strategy(self, tmp_path, monkeypatch):
        """Bad --strategy must exit 2 (invalid args)."""
        from typer.testing import CliRunner

        from engine.cli import app

        monkeypatch.chdir(tmp_path)
        before_json = {
            "lcp_ms": 4200, "cls": 0.18, "inp_ms": 320, "ttfb_ms": 900,
            "images": [],
        }
        (tmp_path / "before.json").write_text(json.dumps(before_json))

        runner = CliRunner()
        result = runner.invoke(app, [
            "compare", "before.json", "https://demo.myshopify.com",
            "--strategy", "tablet",
        ])
        assert result.exit_code == 2

