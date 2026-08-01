"""
CLI integration tests for the user-side TOML config (Sprint 11, TD-2).

Verifies the precedence chain **flag > env var > config > default** at the
CLI boundary: a config value is used when the flag is omitted, an explicit
flag wins, and the env-var layer (PAGESPEED_API_KEY) beats the config.

The config file is injected per-test via ``SHOPIFY_IMAGE_AUDIT_CONFIG`` +
``_reset_config_cache()``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from engine.cli import app
from engine.config import _reset_config_cache
from tests import FIXTURES

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_config_cache() -> None:
    _reset_config_cache()
    yield
    _reset_config_cache()


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """A config.toml whose values differ from every built-in default."""
    path = tmp_path / "config.toml"
    path.write_text(
        """
[defaults]
device = "desktop"
strategy = "desktop"
parallel = 0

[pagespeed]
api_key = "cfg-api-key"

[history]
history_dir = "/tmp/cfg-history"

[report]
output = "cfg-report.html"
brand_color = "#123456"
""",
        encoding="utf-8",
    )
    return path


def _use_config(monkeypatch: pytest.MonkeyPatch, config_file: Path) -> None:
    """Point the CLI at the given config file (fresh cache)."""
    monkeypatch.setenv("SHOPIFY_IMAGE_AUDIT_CONFIG", str(config_file))
    _reset_config_cache()


# ---------------------------------------------------------------------------
# device (run)
# ---------------------------------------------------------------------------


class TestDeviceFromConfig:
    def _run_and_read_meta_device(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config_file: Path,
        tmp_path: Path,
        *extra_args: str,
    ) -> str:
        """Run `audit run` on a fixture and return meta.device from the JSON."""
        _use_config(monkeypatch, config_file)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "run",
                "https://example.com",
                "--lhr",
                str(FIXTURES / "bad_hero_lcp.json"),
                *extra_args,
            ],
        )
        assert result.exit_code == 0, result.stdout
        payload = json.loads((tmp_path / "artifacts" / "audit_result.json").read_text())
        return payload["meta"]["device"]

    def test_config_device_used_when_flag_missing(
        self, monkeypatch: pytest.MonkeyPatch, config_file: Path, tmp_path: Path
    ) -> None:
        assert self._run_and_read_meta_device(monkeypatch, config_file, tmp_path) == "desktop"

    def test_flag_overrides_config_device(
        self, monkeypatch: pytest.MonkeyPatch, config_file: Path, tmp_path: Path
    ) -> None:
        # config says desktop; the flag must win.
        device = self._run_and_read_meta_device(
            monkeypatch,
            config_file,
            tmp_path,
            "--device",
            "mobile",
        )
        assert device == "mobile"


# ---------------------------------------------------------------------------
# api_key (measure): config < env var < flag
# ---------------------------------------------------------------------------


class TestApiKeyFromConfig:
    def _invoke_measure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config_file: Path,
        *args: str,
    ) -> dict:
        captured: dict = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs

            def get_metrics(self, url, strategy):
                captured["strategy"] = strategy
                from integrations.pagespeed_api import PageSpeedMetrics

                return PageSpeedMetrics(
                    lcp=2.5,
                    cls=0.05,
                    inp=0.1,
                    first_contentful_paint=1.2,
                    first_meaningful_paint=1.5,
                    speed_index=1.8,
                    time_to_interactive=3.5,
                    total_blocking_time=150,
                    performance_score=90,
                    url=url,
                    strategy=strategy,
                    fetch_time="2026-01-01T00:00:00Z",
                )

        monkeypatch.setattr("engine.cli.PageSpeedAPIClient", FakeClient)
        _use_config(monkeypatch, config_file)
        result = runner.invoke(app, ["measure", "https://demo.myshopify.com", *args])
        assert result.exit_code == 0, result.stdout
        return captured

    def test_config_api_key_used_when_no_flag_or_env(self, monkeypatch: pytest.MonkeyPatch, config_file: Path) -> None:
        monkeypatch.delenv("PAGESPEED_API_KEY", raising=False)
        captured = self._invoke_measure(monkeypatch, config_file)
        assert captured["client_kwargs"]["api_key"] == "cfg-api-key"

    def test_env_var_beats_config(self, monkeypatch: pytest.MonkeyPatch, config_file: Path) -> None:
        monkeypatch.setenv("PAGESPEED_API_KEY", "env-beats-cfg")
        captured = self._invoke_measure(monkeypatch, config_file)
        assert captured["client_kwargs"]["api_key"] == "env-beats-cfg"

    def test_flag_beats_config(self, monkeypatch: pytest.MonkeyPatch, config_file: Path) -> None:
        captured = self._invoke_measure(monkeypatch, config_file, "--api-key", "flag-beats-all")
        assert captured["client_kwargs"]["api_key"] == "flag-beats-all"

    def test_strategy_from_config(self, monkeypatch: pytest.MonkeyPatch, config_file: Path) -> None:
        monkeypatch.delenv("PAGESPEED_API_KEY", raising=False)
        captured = self._invoke_measure(monkeypatch, config_file)
        assert captured["strategy"] == "desktop"  # config says desktop


# ---------------------------------------------------------------------------
# parallel=0 (schedule run-all) — must survive resolution, no `or` bug
# ---------------------------------------------------------------------------


class TestParallelFromConfig:
    def test_config_parallel_zero_survives(
        self, monkeypatch: pytest.MonkeyPatch, config_file: Path, tmp_path: Path
    ) -> None:
        """parallel=0 (unlimited) from config must reach run_all_schedules."""
        captured: dict = {}

        def fake_run_all(store, *, history_store, api_key, parallel, stop_on_error):
            captured["parallel"] = parallel
            return []

        monkeypatch.setattr("engine.scheduler.run_all_schedules", fake_run_all)
        monkeypatch.setattr("engine.cli.HistoryStore", lambda base_dir=None: object())
        _use_config(monkeypatch, config_file)
        result = runner.invoke(app, ["schedule", "run-all"])
        assert result.exit_code == 0, result.stdout
        assert captured["parallel"] == 0


# ---------------------------------------------------------------------------
# report output from config
# ---------------------------------------------------------------------------


class TestReportOutputFromConfig:
    def test_config_output_used(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config_file: Path,
        tmp_path: Path,
        sample_audit_result,
    ) -> None:
        _use_config(monkeypatch, config_file)
        audit_json = tmp_path / "audit_result.json"
        audit_json.write_text(sample_audit_result.model_dump_json(), encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["report", str(audit_json)])
        assert result.exit_code == 0, result.stdout
        # config [report] output = "cfg-report.html"
        assert (tmp_path / "cfg-report.html").exists()
        assert not (tmp_path / "report.html").exists()

    def test_flag_overrides_config_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
        config_file: Path,
        tmp_path: Path,
        sample_audit_result,
    ) -> None:
        _use_config(monkeypatch, config_file)
        audit_json = tmp_path / "audit_result.json"
        audit_json.write_text(sample_audit_result.model_dump_json(), encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["report", str(audit_json), "-o", "mine.html"])
        assert result.exit_code == 0, result.stdout
        assert (tmp_path / "mine.html").exists()
        assert not (tmp_path / "cfg-report.html").exists()


# ---------------------------------------------------------------------------
# cache TTL from config
# ---------------------------------------------------------------------------


class TestCacheTtlFromConfig:
    def test_cache_ttl_from_config(self, monkeypatch: pytest.MonkeyPatch, config_file: Path) -> None:
        monkeypatch.delenv("PAGESPEED_CACHE_TTL", raising=False)
        _use_config(monkeypatch, config_file)  # no cache_ttl in this file → default
        from integrations._cache import ResponseCache

        assert ResponseCache().ttl == 3600  # built-in default

        # A config with an explicit TTL wins.
        path = config_file.parent / "ttl.toml"
        path.write_text("[pagespeed]\ncache_ttl = 7200\n", encoding="utf-8")
        _use_config(monkeypatch, path)
        assert ResponseCache().ttl == 7200

    def test_env_var_beats_config_ttl(self, monkeypatch: pytest.MonkeyPatch, config_file: Path) -> None:
        monkeypatch.setenv("PAGESPEED_CACHE_TTL", "123")
        path = config_file.parent / "ttl.toml"
        path.write_text("[pagespeed]\ncache_ttl = 7200\n", encoding="utf-8")
        _use_config(monkeypatch, path)
        from integrations._cache import ResponseCache

        assert ResponseCache().ttl == 123
