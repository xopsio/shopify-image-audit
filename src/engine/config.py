"""
User-side TOML configuration (Sprint 11, TD-1).

Reads ``config.toml`` from the XDG config dir (``$XDG_CONFIG_HOME/
shopify-image-audit/config.toml``, falling back to ``~/.config/
shopify-image-audit/config.toml``). The path can be overridden with the
``SHOPIFY_IMAGE_AUDIT_CONFIG`` env var.

Precedence is **CLI flag > env var > config file > default** — this
module only provides the config-file layer; flag/env precedence is
handled by Typer at the call sites.

Design:
- ``Config`` is a frozen dataclass so defaults are immutable.
- ``load_config()`` is a pure function; ``get_config()`` caches the
  result so the CLI can read it cheaply per command (``_reset_config_cache``
  exists for tests).
- Malformed TOML, unknown keys, and out-of-range values degrade to a
  warning + default instead of failing the run.
"""

from __future__ import annotations

import functools
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from engine._logging import get_logger

_log = get_logger()

#: Env var that overrides the config file location entirely.
CONFIG_ENV_VAR = "SHOPIFY_IMAGE_AUDIT_CONFIG"

#: Allowed values for device/strategy — everything else is rejected.
_VALID_DEVICES = ("mobile", "desktop")


@dataclass(frozen=True)
class DefaultsConfig:
    """Per-run defaults shared across commands.

    ``no_cache`` / ``stop_on_error`` are deliberately NOT configurable:
    boolean flags have no reliable "unset" form in Typer, so a config
    value could never be overridden back off from the CLI.
    """

    device: str = "mobile"
    strategy: str = "mobile"
    parallel: int = 1


@dataclass(frozen=True)
class PageSpeedConfig:
    """PageSpeed Insights settings."""

    api_key: str | None = None
    cache_ttl: int | None = None  # None = env var / built-in default


@dataclass(frozen=True)
class ShopifyConfig:
    """Shopify Admin API settings."""

    access_token: str | None = None
    # OAuth-flow credentials (Sprint 19). ``client_id`` / ``client_secret``
    # come from a custom app in the Shopify Partner dashboard.
    client_id: str | None = None
    client_secret: str | None = None
    # Full callback URL registered in the Partner dashboard. Defaults to
    # the loopback URL the embedded callback server binds to.
    redirect_uri: str | None = None
    # Comma-separated scope list forwarded to Shopify's authorize URL.
    scopes: str = "read_products,read_themes,read_shop"


@dataclass(frozen=True)
class HistoryConfig:
    """Where audit history is stored."""

    history_dir: str | None = None


@dataclass(frozen=True)
class ReportConfig:
    """Branding and output defaults for HTML/PDF reports."""

    output: str = "report.html"
    brand_color: str | None = None
    brand_logo: str | None = None


@dataclass(frozen=True)
class Config:
    """Root config object — mirrors the sections of ``config.toml``."""

    defaults: DefaultsConfig = DefaultsConfig()
    pagespeed: PageSpeedConfig = PageSpeedConfig()
    shopify: ShopifyConfig = ShopifyConfig()
    history: HistoryConfig = HistoryConfig()
    report: ReportConfig = ReportConfig()


def default_config_path() -> Path:
    """Return the default config file location (XDG config dir)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "shopify-image-audit" / "config.toml"


def _warn_bad_value(key: str, value: object, expected: str) -> None:
    _log.warning(
        "Config: ignoring invalid %r (%r) — expected %s",
        key,
        value,
        expected,
    )


def _parse_section(
    raw: dict[str, object],
    key: str,
    *,
    expected: type,
    default: object,
) -> object:
    """Fetch ``raw[key]`` validating its type; fall back to default."""
    value = raw.get(key)
    if value is None:
        return default
    if not isinstance(value, expected):
        _warn_bad_value(key, value, expected.__name__)
        return default
    return value


def load_config(path: Path | None = None) -> Config:
    """Load and validate ``config.toml`` from ``path`` (or the default).

    Missing file, unparsable TOML, unknown keys and invalid values all
    degrade to warnings + defaults — a broken config never blocks a run.
    """
    if path is None:
        override = os.environ.get(CONFIG_ENV_VAR)
        path = Path(override) if override else default_config_path()

    if not path.is_file():
        return Config()

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        _log.warning("Config: cannot read %s (%s) — using defaults", path, exc)
        return Config()

    # Reject unknown top-level sections (typo protection).
    known_sections = {"defaults", "pagespeed", "shopify", "history", "report"}
    for section in raw:
        if section not in known_sections:
            _log.warning("Config: unknown section [%s] ignored", section)

    defaults_raw = raw.get("defaults", {})
    defaults_raw = defaults_raw if isinstance(defaults_raw, dict) else {}

    device = _parse_section(defaults_raw, "device", expected=str, default="mobile")
    assert isinstance(device, str)
    if device not in _VALID_DEVICES:
        _warn_bad_value("defaults.device", device, "mobile|desktop")
        device = "mobile"

    strategy = _parse_section(defaults_raw, "strategy", expected=str, default="mobile")
    assert isinstance(strategy, str)
    if strategy not in _VALID_DEVICES:
        _warn_bad_value("defaults.strategy", strategy, "mobile|desktop")
        strategy = "mobile"

    parallel = _parse_section(defaults_raw, "parallel", expected=int, default=1)
    assert isinstance(parallel, int)
    if parallel < 0:
        _warn_bad_value("defaults.parallel", parallel, ">= 0")
        parallel = 1

    pagespeed_raw = raw.get("pagespeed", {})
    pagespeed_raw = pagespeed_raw if isinstance(pagespeed_raw, dict) else {}
    api_key = _parse_section(pagespeed_raw, "api_key", expected=str, default=None)
    cache_ttl = _parse_section(pagespeed_raw, "cache_ttl", expected=int, default=None)
    assert cache_ttl is None or isinstance(cache_ttl, int)
    if cache_ttl is not None and cache_ttl < 0:
        _warn_bad_value("pagespeed.cache_ttl", cache_ttl, ">= 0")
        cache_ttl = None

    shopify_raw = raw.get("shopify", {})
    shopify_raw = shopify_raw if isinstance(shopify_raw, dict) else {}
    access_token = _parse_section(shopify_raw, "access_token", expected=str, default=None)

    history_raw = raw.get("history", {})
    history_raw = history_raw if isinstance(history_raw, dict) else {}
    history_dir = _parse_section(history_raw, "history_dir", expected=str, default=None)

    report_raw = raw.get("report", {})
    report_raw = report_raw if isinstance(report_raw, dict) else {}
    output = _parse_section(report_raw, "output", expected=str, default="report.html")
    brand_color = _parse_section(report_raw, "brand_color", expected=str, default=None)
    brand_logo = _parse_section(report_raw, "brand_logo", expected=str, default=None)

    assert api_key is None or isinstance(api_key, str)
    assert access_token is None or isinstance(access_token, str)
    assert history_dir is None or isinstance(history_dir, str)
    assert isinstance(output, str)
    assert brand_color is None or isinstance(brand_color, str)
    assert brand_logo is None or isinstance(brand_logo, str)

    return Config(
        defaults=DefaultsConfig(
            device=device,
            strategy=strategy,
            parallel=parallel,
        ),
        pagespeed=PageSpeedConfig(api_key=api_key, cache_ttl=cache_ttl),
        shopify=ShopifyConfig(access_token=access_token),
        history=HistoryConfig(history_dir=history_dir),
        report=ReportConfig(output=output, brand_color=brand_color, brand_logo=brand_logo),
    )


@functools.lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the cached config (loaded once per process)."""
    return load_config()


def _reset_config_cache() -> None:
    """Drop the cached config — used by tests that swap config files."""
    get_config.cache_clear()
