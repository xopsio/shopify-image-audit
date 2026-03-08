"""
Tests for CLI input safety guards (URL scheme, --out-dir validation).
Verifies that invalid inputs produce exit code 2.
"""
from __future__ import annotations

import pytest
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
        result = runner.invoke(app, ["run", "https://example.com", "--out-dir", "/absolute/path"])
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
        from engine.cli import app
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["report", "nonexistent.json"])
        assert result.exit_code == 2
        assert "not found" in result.stdout.lower()

    def test_report_invalid_json(self, tmp_path):
        """report should exit with code 2 if input is not valid JSON."""
        from engine.cli import app
        from typer.testing import CliRunner

        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{invalid json}")

        runner = CliRunner()
        result = runner.invoke(app, ["report", str(bad_json)])
        assert result.exit_code == 2
        assert "invalid json" in result.stdout.lower()

    def test_report_success(self, tmp_path):
        """report should generate HTML successfully with valid input."""
        import json
        from engine.cli import app
        from typer.testing import CliRunner

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
        from engine.cli import app
        from typer.testing import CliRunner

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
        from engine.cli import app
        from typer.testing import CliRunner

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
        from engine.cli import app
        from typer.testing import CliRunner

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
        from engine.cli import app
        from typer.testing import CliRunner

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

