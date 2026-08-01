"""
CLI tests for ``audit shopify login`` (Sprint 22, TD-3).

Closes the Sprint 19 testing gap: the OAuth login flow had no
CLI-level coverage. The embedded callback server is replaced with a
fake context manager (the real server is covered by
``tests/test_oauth_callback_server.py``), the token exchange is
stubbed, and ``TokensStore`` is real but redirected to a tmp dir with
encryption disabled (CI has no D-Bus / Secret Service).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from engine.cli import app
from engine.tokens import TokensStore

runner = CliRunner()

_CLIENT_ID = "cid"
_CLIENT_SECRET = "shpss_secret"


@pytest.fixture
def token_store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``TokensStore`` to a tmp path without a keyring."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("SHOPIFY_AUDIT_TOKENS_DISABLED", "1")
    return tmp_path


class _FakeOAuthServer:
    """Context-manager stand-in for :class:`OAuthCallbackServer`.

    ``wait_for_code()`` pops the next outcome from the shared queue;
    ``None`` simulates a timeout or denial on Shopify's side.
    """

    def __init__(self, outcomes: list[str | None]) -> None:
        self._outcomes = outcomes
        self.callback_url = "http://localhost:18765/callback"

    def __enter__(self) -> _FakeOAuthServer:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def wait_for_code(self) -> str | None:
        return self._outcomes.pop(0) if self._outcomes else None

    def last_error(self) -> str | None:
        return None


@pytest.fixture
def oauth_mocks(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """Patch the OAuth machinery; returns the per-store outcome queue.

    The production flow lazy-imports these names inside the function,
    so patching the module attributes is sufficient.
    """
    outcomes: list[str | None] = []

    monkeypatch.setattr("webbrowser.open", lambda url: True)
    monkeypatch.setattr(
        "integrations.oauth_callback_server.OAuthCallbackServer",
        lambda state, *, timeout=60.0: _FakeOAuthServer(outcomes),
    )

    def fake_exchange(*, shop: str, code: str, client_id: str, client_secret: str) -> str:
        return f"shpat_{shop.split('.')[0]}"

    monkeypatch.setattr("integrations.shopify_oauth.exchange_code_for_token", fake_exchange)
    return outcomes


def _write_stores(tmp_path: Path, entries: list[dict[str, str]]) -> Path:
    path = tmp_path / "stores.json"
    path.write_text(json.dumps(entries))
    return path


# ---------------------------------------------------------------------------
# Single-store login (regression: pre-Sprint-22 behavior)
# ---------------------------------------------------------------------------


class TestLoginSingle:
    def test_single_store_happy_path(self, oauth_mocks: list[str | None], token_store_dir: Path) -> None:
        oauth_mocks.append("temp_code_1")
        result = runner.invoke(
            app,
            ["shopify", "login", "a.myshopify.com", "--client-id", _CLIENT_ID, "--client-secret", _CLIENT_SECRET],
        )
        assert result.exit_code == 0, result.stdout
        assert "Authorised a.myshopify.com" in result.stdout
        assert "Next: `audit shopify auth a.myshopify.com`" in result.stdout
        assert TokensStore().get("a.myshopify.com") == "shpat_a"

    def test_missing_domain_and_file_exits_2(self, oauth_mocks: list[str | None]) -> None:
        result = runner.invoke(
            app,
            ["shopify", "login", "--client-id", _CLIENT_ID, "--client-secret", _CLIENT_SECRET],
        )
        assert result.exit_code == 2
        assert "--stores-file" in result.stdout

    def test_missing_credentials_exits_2(self, oauth_mocks: list[str | None]) -> None:
        result = runner.invoke(app, ["shopify", "login", "a.myshopify.com"])
        assert result.exit_code == 2
        assert "OAuth credentials missing" in result.stdout

    def test_both_domain_and_file_exits_2(self, oauth_mocks: list[str | None], tmp_path: Path) -> None:
        stores_file = _write_stores(tmp_path, [{"shop_domain": "a.myshopify.com"}])
        result = runner.invoke(
            app,
            [
                "shopify",
                "login",
                "a.myshopify.com",
                "--stores-file",
                str(stores_file),
                "--client-id",
                _CLIENT_ID,
                "--client-secret",
                _CLIENT_SECRET,
            ],
        )
        assert result.exit_code == 2
        assert "not both" in result.stdout

    def test_timeout_exits_2(self, oauth_mocks: list[str | None], token_store_dir: Path) -> None:
        oauth_mocks.append(None)  # no callback received
        result = runner.invoke(
            app,
            ["shopify", "login", "a.myshopify.com", "--client-id", _CLIENT_ID, "--client-secret", _CLIENT_SECRET],
        )
        assert result.exit_code == 2
        assert "OAuth timed out" in result.stdout
        assert TokensStore().get("a.myshopify.com") is None


# ---------------------------------------------------------------------------
# Multi-store login via --stores-file (Sprint 22)
# ---------------------------------------------------------------------------


class TestLoginStoresFile:
    def test_happy_path_two_stores(
        self,
        oauth_mocks: list[str | None],
        token_store_dir: Path,
        tmp_path: Path,
    ) -> None:
        oauth_mocks.extend(["code_a", "code_b"])
        stores_file = _write_stores(
            tmp_path,
            [
                {"shop_domain": "a.myshopify.com"},
                {"shop_domain": "b.myshopify.com"},
            ],
        )
        result = runner.invoke(
            app,
            [
                "shopify",
                "login",
                "--stores-file",
                str(stores_file),
                "--client-id",
                _CLIENT_ID,
                "--client-secret",
                _CLIENT_SECRET,
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert "(1/2)" in result.stdout
        assert "(2/2)" in result.stdout
        assert "2 stores authorised" in result.stdout
        assert TokensStore().get("a.myshopify.com") == "shpat_a"
        assert TokensStore().get("b.myshopify.com") == "shpat_b"

    def test_partial_failure_summary(
        self,
        oauth_mocks: list[str | None],
        token_store_dir: Path,
        tmp_path: Path,
    ) -> None:
        # Second store times out — the first must still be persisted.
        oauth_mocks.extend(["code_a", None])
        stores_file = _write_stores(
            tmp_path,
            [
                {"shop_domain": "a.myshopify.com"},
                {"shop_domain": "b.myshopify.com"},
            ],
        )
        result = runner.invoke(
            app,
            [
                "shopify",
                "login",
                "--stores-file",
                str(stores_file),
                "--client-id",
                _CLIENT_ID,
                "--client-secret",
                _CLIENT_SECRET,
            ],
        )
        assert result.exit_code == 2
        assert "1 authorised, 1 failed" in result.stdout
        assert TokensStore().get("a.myshopify.com") == "shpat_a"
        assert TokensStore().get("b.myshopify.com") is None

    def test_all_failed_exits_2(
        self,
        oauth_mocks: list[str | None],
        token_store_dir: Path,
        tmp_path: Path,
    ) -> None:
        oauth_mocks.extend([None, None])
        stores_file = _write_stores(
            tmp_path,
            [
                {"shop_domain": "a.myshopify.com"},
                {"shop_domain": "b.myshopify.com"},
            ],
        )
        result = runner.invoke(
            app,
            [
                "shopify",
                "login",
                "--stores-file",
                str(stores_file),
                "--client-id",
                _CLIENT_ID,
                "--client-secret",
                _CLIENT_SECRET,
            ],
        )
        assert result.exit_code == 2
        assert "0 authorised, 2 failed" in result.stdout

    def test_empty_file_exits_0(
        self,
        oauth_mocks: list[str | None],
        token_store_dir: Path,
        tmp_path: Path,
    ) -> None:
        stores_file = _write_stores(tmp_path, [])
        result = runner.invoke(
            app,
            [
                "shopify",
                "login",
                "--stores-file",
                str(stores_file),
                "--client-id",
                _CLIENT_ID,
                "--client-secret",
                _CLIENT_SECRET,
            ],
        )
        assert result.exit_code == 0
        assert "No stores found" in result.stdout

    def test_invalid_json_exits_2(self, oauth_mocks: list[str | None], tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        result = runner.invoke(
            app,
            [
                "shopify",
                "login",
                "--stores-file",
                str(bad),
                "--client-id",
                _CLIENT_ID,
                "--client-secret",
                _CLIENT_SECRET,
            ],
        )
        assert result.exit_code == 2
        assert "Invalid JSON" in result.stdout

    def test_entry_missing_shop_domain_exits_2(
        self,
        oauth_mocks: list[str | None],
        tmp_path: Path,
    ) -> None:
        stores_file = _write_stores(tmp_path, [{"access_token": "shpat_x"}])
        result = runner.invoke(
            app,
            [
                "shopify",
                "login",
                "--stores-file",
                str(stores_file),
                "--client-id",
                _CLIENT_ID,
                "--client-secret",
                _CLIENT_SECRET,
            ],
        )
        assert result.exit_code == 2
        assert "Missing required key 'shop_domain'" in result.stdout

    def test_access_token_in_file_is_ignored(
        self,
        oauth_mocks: list[str | None],
        token_store_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Login always runs OAuth — an access_token in the file is not reused."""
        oauth_mocks.append("code_a")
        stores_file = _write_stores(
            tmp_path,
            [{"shop_domain": "a.myshopify.com", "access_token": "shpat_explicit"}],
        )
        result = runner.invoke(
            app,
            [
                "shopify",
                "login",
                "--stores-file",
                str(stores_file),
                "--client-id",
                _CLIENT_ID,
                "--client-secret",
                _CLIENT_SECRET,
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert TokensStore().get("a.myshopify.com") == "shpat_a"
