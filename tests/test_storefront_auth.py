"""
Tests for the storefront-password authentication flow (Sprint 25).

Covers the new ``integrations.storefront_auth`` module and the
``--storefront-password`` CLI option:

- ``authenticate_storefront`` success / wrong-password / hCaptcha /
  network / missing-cookie / unexpected-response cases
- ``_run_lighthouse`` adds ``--extra-headers`` only when given
- End-to-end CLI: ``audit run --storefront-password`` posts the
  password form and threads the cookie into the Lighthouse cmd

All HTTP is mocked with ``responses`` (already in the test deps) — no
network calls leave the test process.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests
import responses
from typer.testing import CliRunner

from engine.cli import (
    EXIT_INVALID_ARGS,
    _run_lighthouse,
    app,
)
from integrations.storefront_auth import (
    COOKIE_NAME,
    StorefrontCaptchaError,
    StorefrontMissingCookieError,
    StorefrontNetworkError,
    StorefrontSession,
    StorefrontUnexpectedResponseError,
    StorefrontWrongPasswordError,
    authenticate_storefront,
)

runner = CliRunner()

SHOP = "visualgain.myshopify.com"
PASSWORD = "supersecret"
PASSWORD_URL = f"https://{SHOP}/password"


@pytest.fixture
def mocked_responses() -> responses.RequestsMock:
    """Activate ``responses`` for the duration of a single test.

    Used as a method-level fixture so the @responses.activate class
    decorator — which has compatibility quirks with newer pytest — is
    not needed. All tests in this file that hit the network must
    request this fixture.
    """
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


# ---------------------------------------------------------------------------
# authenticate_storefront — pure HTTP path (no CLI)
# ---------------------------------------------------------------------------


class TestAuthenticateStorefront:
    def test_success_returns_session_with_cookie(self, mocked_responses) -> None:
        # 302 with Location header AND the auth cookie → success.
        mocked_responses.add(
            responses.POST,
            PASSWORD_URL,
            status=302,
            headers={
                "location": "/",
                "set-cookie": f"{COOKIE_NAME}=abc123def456; Max-Age=31536000; HttpOnly; Secure; SameSite=Lax; Path=/",
            },
        )
        session = authenticate_storefront(SHOP, PASSWORD)
        assert isinstance(session, StorefrontSession)
        assert session.shop_domain == SHOP
        assert session.cookie_header == f"{COOKIE_NAME}=abc123def456"
        # The form fields were posted.
        body = mocked_responses.calls[0].request.body
        assert isinstance(body, str)
        assert "form_type=storefront_password" in body
        assert f"password={PASSWORD}" in body

    def test_wrong_password_raises_typed_error(self, mocked_responses) -> None:
        mocked_responses.add(
            responses.POST,
            PASSWORD_URL,
            status=200,
            headers={"set-cookie": f"{COOKIE_NAME}=unchanged; Path=/"},
            body="<html>password form</html>",
        )
        with pytest.raises(StorefrontWrongPasswordError, match="Wrong storefront password"):
            authenticate_storefront(SHOP, "WRONG")

    def test_hcaptcha_in_response_raises_captcha_error(self, mocked_responses) -> None:
        mocked_responses.add(
            responses.POST,
            PASSWORD_URL,
            status=200,
            body="<html>please solve hCaptcha to continue</html>",
        )
        with pytest.raises(StorefrontCaptchaError, match="captcha"):
            authenticate_storefront(SHOP, PASSWORD)

    def test_redirect_without_cookie_raises_missing_cookie(self, mocked_responses) -> None:
        mocked_responses.add(
            responses.POST,
            PASSWORD_URL,
            status=302,
            headers={"location": "/"},
        )
        with pytest.raises(StorefrontMissingCookieError, match="did not set"):
            authenticate_storefront(SHOP, PASSWORD)

    def test_unexpected_status_raises_unexpected_error(self, mocked_responses) -> None:
        mocked_responses.add(
            responses.POST,
            PASSWORD_URL,
            status=500,
            body="internal server error",
        )
        with pytest.raises(StorefrontUnexpectedResponseError, match="HTTP 500"):
            authenticate_storefront(SHOP, PASSWORD)

    def test_network_error_raises_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Stub requests.post to raise a transport error. We bypass
        # the ``responses`` library here because it does not expose a
        # clean way to inject ``ConnectionError`` for a registered
        # URL — and the production code only catches
        # ``requests.RequestException`` and its subclasses.
        def fake_post(*args, **kwargs):
            raise requests.RequestException("dns lookup failed")

        monkeypatch.setattr("integrations.storefront_auth.requests.post", fake_post)
        with pytest.raises(StorefrontNetworkError, match="Network error"):
            authenticate_storefront(SHOP, PASSWORD)


# ---------------------------------------------------------------------------
# _run_lighthouse — extra_headers threading
# ---------------------------------------------------------------------------


class TestRunLighthouseExtraHeaders:
    def test_extra_headers_added_to_cmd_when_provided(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = tmp_path / "lh"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            out_arg = next(t for t in cmd if t.startswith("--output-path="))
            out_path = Path(out_arg.split("=", 1)[1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("{}", encoding="utf-8")

        monkeypatch.setattr("engine.cli.subprocess.run", fake_run)
        _run_lighthouse(
            "https://example.com",
            device="mobile",
            runs=1,
            out_dir=tmp_path,
            lighthouse_bin=fake,
            extra_headers={"Cookie": "_shopify_essential=abc"},
        )
        cmd = captured[0]
        # Find the --extra-headers arg; Lighthouse accepts the JSON inline.
        eh_arg = next(t for t in cmd if t.startswith("--extra-headers="))
        payload = json.loads(eh_arg.split("=", 1)[1])
        assert payload == {"Cookie": "_shopify_essential=abc"}

    def test_no_extra_headers_arg_when_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = tmp_path / "lh"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            out_arg = next(t for t in cmd if t.startswith("--output-path="))
            out_path = Path(out_arg.split("=", 1)[1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("{}", encoding="utf-8")

        monkeypatch.setattr("engine.cli.subprocess.run", fake_run)
        _run_lighthouse(
            "https://example.com",
            device="mobile",
            runs=1,
            out_dir=tmp_path,
            lighthouse_bin=fake,
        )
        assert not any(t.startswith("--extra-headers=") for t in captured[0])


# ---------------------------------------------------------------------------
# End-to-end CLI: --storefront-password
# ---------------------------------------------------------------------------


class TestStorefrontPasswordCli:
    def test_run_with_password_threads_cookie_into_lighthouse_cmd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocked_responses: responses.RequestsMock
    ) -> None:
        # Mock the auth POST
        mocked_responses.add(
            responses.POST,
            PASSWORD_URL,
            status=302,
            headers={
                "location": "/",
                "set-cookie": f"{COOKIE_NAME}=xyz999; HttpOnly; Secure",
            },
        )
        # Mock the lighthouse subprocess
        fake_lh = tmp_path / "lh"
        fake_lh.write_text("#!/bin/sh\n", encoding="utf-8")
        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            captured.append(list(cmd))
            out_arg = next(t for t in cmd if t.startswith("--output-path="))
            out_path = Path(out_arg.split("=", 1)[1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            # Minimal fixture so run_audit has something to parse.
            out_path.write_text(
                json.dumps(
                    {
                        "audits": {
                            "image-elements": {
                                "details": {
                                    "items": [
                                        {
                                            "url": "https://cdn.example.com/x.jpg",
                                            "resourceSize": 5000,
                                            "mimeType": "image/webp",
                                        }
                                    ]
                                }
                            }
                        },
                        "categories": {"performance": {"score": 0.9}},
                    }
                ),
                encoding="utf-8",
            )

        monkeypatch.setattr("engine.cli.subprocess.run", fake_run)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "run",
                f"https://{SHOP}/password",  # user passed the password page
                "--storefront-password",
                PASSWORD,
                "--lighthouse-bin",
                str(fake_lh),
                "--out-dir",
                "artifacts",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert "Authenticated as visualgain.myshopify.com" in result.stdout
        # The Lighthouse cmd was called with the cookie.
        assert any(t.startswith("--extra-headers=") and "_shopify_essential=xyz999" in t for t in captured[0])
        # The URL passed to Lighthouse is the storefront root, not /password.
        assert captured[0][1] == "https://visualgain.myshopify.com/"

    def test_run_with_wrong_password_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocked_responses
    ) -> None:
        mocked_responses.add(
            responses.POST,
            PASSWORD_URL,
            status=200,
            body="<html>password form</html>",
        )
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "run",
                f"https://{SHOP}/",
                "--storefront-password",
                "wrong",
            ],
        )
        assert result.exit_code == EXIT_INVALID_ARGS
        assert "Wrong storefront password" in result.stdout
