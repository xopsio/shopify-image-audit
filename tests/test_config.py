"""
Tests for ``src/engine/config.py`` (Sprint 11, TD-1) — user-side TOML config.

Covers:
- default path resolution (XDG_CONFIG_HOME + ~/.config fallback)
- missing file / unparsable TOML / unknown keys / invalid values → defaults
- valid TOML read across all five sections
- SHOPIFY_IMAGE_AUDIT_CONFIG env var override
- CLI integration is covered in test_cli_config.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.config import (
    Config,
    _reset_config_cache,
    default_config_path,
    get_config,
    load_config,
)

SAMPLE_TOML = """
[defaults]
device = "desktop"
strategy = "desktop"
parallel = 4

[pagespeed]
api_key = "cfg-secret"
cache_ttl = 7200

[shopify]
access_token = "shpat_cfg"

[history]
history_dir = "/var/lib/audit-history"

[report]
output = "custom-report.html"
brand_color = "#ff6b35"
brand_logo = "/etc/audit/logo.png"
"""


@pytest.fixture(autouse=True)
def _clean_config_cache() -> None:
    """Every test starts with a fresh (uncached) config."""
    _reset_config_cache()
    yield
    _reset_config_cache()


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


class TestDefaultConfigPath:
    def test_uses_xdg_config_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg-config")
        assert default_config_path() == (Path("/tmp/xdg-config") / "shopify-image-audit" / "config.toml")

    def test_falls_back_to_home_dot_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert default_config_path() == (Path.home() / ".config" / "shopify-image-audit" / "config.toml")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path / "nope.toml")
        assert cfg == Config()

    def test_valid_toml_reads_all_sections(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text(SAMPLE_TOML, encoding="utf-8")
        cfg = load_config(path)
        assert cfg.defaults.device == "desktop"
        assert cfg.defaults.strategy == "desktop"
        assert cfg.defaults.parallel == 4
        assert cfg.pagespeed.api_key == "cfg-secret"
        assert cfg.pagespeed.cache_ttl == 7200
        assert cfg.shopify.access_token == "shpat_cfg"
        assert cfg.history.history_dir == "/var/lib/audit-history"
        assert cfg.report.output == "custom-report.html"
        assert cfg.report.brand_color == "#ff6b35"
        assert cfg.report.brand_logo == "/etc/audit/logo.png"

    def test_invalid_toml_degrades_to_defaults(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        path = tmp_path / "config.toml"
        path.write_text("[defaults\ndevice = ", encoding="utf-8")  # malformed
        with caplog.at_level("WARNING"):
            cfg = load_config(path)
        assert cfg == Config()
        assert "cannot read" in caplog.text

    def test_unknown_section_warns_but_keeps_known(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        path = tmp_path / "config.toml"
        path.write_text('[typo_section]\nx = 1\n\n[defaults]\ndevice = "desktop"\n', encoding="utf-8")
        with caplog.at_level("WARNING"):
            cfg = load_config(path)
        assert cfg.defaults.device == "desktop"
        assert "unknown section" in caplog.text

    def test_invalid_device_falls_back_to_mobile(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        path = tmp_path / "config.toml"
        path.write_text('[defaults]\ndevice = "tablet"\n', encoding="utf-8")
        with caplog.at_level("WARNING"):
            cfg = load_config(path)
        assert cfg.defaults.device == "mobile"
        assert "invalid" in caplog.text

    def test_invalid_parallel_falls_back(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text("[defaults]\nparallel = -3\n", encoding="utf-8")
        assert load_config(path).defaults.parallel == 1

    def test_negative_cache_ttl_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text("[pagespeed]\ncache_ttl = -10\n", encoding="utf-8")
        assert load_config(path).pagespeed.cache_ttl is None

    def test_wrong_type_falls_back(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text('[defaults]\nparallel = "many"\n', encoding="utf-8")
        assert load_config(path).defaults.parallel == 1

    def test_env_var_override_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "elsewhere.toml"
        path.write_text('[defaults]\ndevice = "desktop"\n', encoding="utf-8")
        monkeypatch.setenv("SHOPIFY_IMAGE_AUDIT_CONFIG", str(path))
        cfg = load_config()  # no explicit path → env var wins
        assert cfg.defaults.device == "desktop"

    def test_get_config_caches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "config.toml"
        path.write_text('[defaults]\ndevice = "desktop"\n', encoding="utf-8")
        monkeypatch.setenv("SHOPIFY_IMAGE_AUDIT_CONFIG", str(path))
        first = get_config()
        # Mutating the file must NOT change the cached result.
        path.write_text('[defaults]\ndevice = "mobile"\n', encoding="utf-8")
        assert get_config() is first
        assert first.defaults.device == "desktop"
