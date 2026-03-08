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
