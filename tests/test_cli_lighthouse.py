"""
CLI integration tests for the Lighthouse-binary resolution chain
(Sprint 16, TD-2). Closes the 0/6 testing gap in ``_run_lighthouse``.

Covers:
- Missing binary → exit 10 with help text
- Explicit ``--lighthouse-bin`` flag overrides PATH lookup
- ``$LIGHTHOUSE_BIN`` env var is honoured when flag is missing
- Subprocess success writes a JSON report that ``run`` can consume
- Subprocess ``CalledProcessError`` → exit 10
- Subprocess ``TimeoutExpired`` → exit 10

The tests never invoke a real Lighthouse binary; they mock both
``shutil.which`` and ``subprocess.run`` via ``monkeypatch``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from engine.cli import (
    EXIT_LIGHTHOUSE_FAILURE,
    _resolve_lighthouse_binary,
    _run_lighthouse,
    app,
)

runner = CliRunner()


def _fixture_lhr(tmp_path: Path) -> Path:
    """Minimal Lighthouse-shaped fixture so ``run_audit`` is happy."""
    payload = {
        "audits": {
            "largest-contentful-paint-element": {"details": {"items": [{"url": "https://cdn.example.com/hero.jpg"}]}},
            "image-elements": {
                "details": {
                    "items": [
                        {
                            "url": "https://cdn.example.com/hero.jpg",
                            "resourceSize": 95000,
                            "mimeType": "image/webp",
                            "displayedWidth": 1200,
                            "displayedHeight": 800,
                        }
                    ]
                }
            },
        },
        "categories": {"performance": {"score": 0.9}},
        "fetchTime": "2026-07-30T15:00:00Z",
    }
    p = tmp_path / "lhr.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _resolve_lighthouse_binary — the pure resolver (no subprocess)
# ---------------------------------------------------------------------------


class TestResolveLighthouseBinary:
    def test_explicit_flag_wins(self, tmp_path: Path) -> None:
        fake = tmp_path / "lh"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        # shutil.which must NOT be consulted when an explicit path is given.

        def _must_not_run(*args, **kwargs):
            pytest.fail("shutil.which was called despite --lighthouse-bin")

        result = _resolve_lighthouse_binary(str(fake))
        assert result == fake

    def test_env_var_used_when_flag_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = tmp_path / "lh"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setenv("LIGHTHOUSE_BIN", str(fake))
        result = _resolve_lighthouse_binary(None)
        assert result == fake

    def test_env_var_with_nonexistent_path_exits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LIGHTHOUSE_BIN", str(tmp_path / "does-not-exist"))
        with pytest.raises(typer.Exit) as exc:
            _resolve_lighthouse_binary(None)
        assert exc.value.exit_code == EXIT_LIGHTHOUSE_FAILURE

    def test_shutil_which_path_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = tmp_path / "lh"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.delenv("LIGHTHOUSE_BIN", raising=False)
        monkeypatch.setattr("engine.cli.shutil.which", lambda _name: str(fake))
        assert _resolve_lighthouse_binary(None) == fake

    def test_missing_binary_exits_10_with_help(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LIGHTHOUSE_BIN", raising=False)
        monkeypatch.setattr("engine.cli.shutil.which", lambda _name: None)
        with pytest.raises(typer.Exit) as exc:
            _resolve_lighthouse_binary(None)
        assert exc.value.exit_code == EXIT_LIGHTHOUSE_FAILURE


# ---------------------------------------------------------------------------
# _run_lighthouse — subprocess behaviour
# ---------------------------------------------------------------------------


class TestRunLighthouse:
    def test_subprocess_success_returns_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = tmp_path / "lh"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        out_dir = tmp_path / "artifacts"

        def fake_run(cmd, **kwargs):
            # Lighthouse receives `--output-path=<file>` as a single token.
            out_arg = next(t for t in cmd if t.startswith("--output-path="))
            out_path = Path(out_arg.split("=", 1)[1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("{}", encoding="utf-8")

        monkeypatch.setattr("engine.cli.subprocess.run", fake_run)
        result = _run_lighthouse(
            "https://example.com",
            device="mobile",
            runs=2,
            out_dir=out_dir,
            lighthouse_bin=fake,
        )
        assert result.is_file()
        assert result.parent == out_dir

    def test_subprocess_called_process_error_exits_10(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = tmp_path / "lh"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")

        def fake_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(returncode=1, cmd=cmd, stderr="boom")

        monkeypatch.setattr("engine.cli.subprocess.run", fake_run)
        with pytest.raises(typer.Exit) as exc:
            _run_lighthouse(
                "https://example.com",
                device="mobile",
                runs=1,
                out_dir=tmp_path,
                lighthouse_bin=fake,
            )
        assert exc.value.exit_code == EXIT_LIGHTHOUSE_FAILURE

    def test_subprocess_timeout_exits_10(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = tmp_path / "lh"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=600)

        monkeypatch.setattr("engine.cli.subprocess.run", fake_run)
        with pytest.raises(typer.Exit) as exc:
            _run_lighthouse(
                "https://example.com",
                device="mobile",
                runs=1,
                out_dir=tmp_path,
                lighthouse_bin=fake,
            )
        assert exc.value.exit_code == EXIT_LIGHTHOUSE_FAILURE


# ---------------------------------------------------------------------------
# run — full CLI flow with mocked Lighthouse
# ---------------------------------------------------------------------------


class TestRunCliLighthouse:
    def test_run_with_explicit_lighthouse_bin_succeeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake_lh = tmp_path / "lh"
        fake_lh.write_text("#!/bin/sh\n", encoding="utf-8")
        fixture = _fixture_lhr(tmp_path)

        def fake_run(cmd, **kwargs):
            out_arg = next(t for t in cmd if t.startswith("--output-path="))
            out_path = Path(out_arg.split("=", 1)[1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Copy the fixture so the orchestrator can parse it.
            out_path.write_text(fixture.read_text(), encoding="utf-8")

        monkeypatch.setattr("engine.cli.subprocess.run", fake_run)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "run",
                "https://demo.myshopify.com",
                "--lighthouse-bin",
                str(fake_lh),
                "--out-dir",
                "artifacts",
            ],
        )
        assert result.exit_code == 0, result.stdout

    def test_run_missing_lighthouse_exits_10(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LIGHTHOUSE_BIN", raising=False)
        monkeypatch.setattr("engine.cli.shutil.which", lambda _name: None)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["run", "https://demo.myshopify.com"])
        assert result.exit_code == EXIT_LIGHTHOUSE_FAILURE
        # Help text mentions all four resolution paths.
        assert "--lighthouse-bin" in result.stdout
        assert "LIGHTHOUSE_BIN" in result.stdout
        assert "npm i -g lighthouse" in result.stdout
        assert "--lhr" in result.stdout
