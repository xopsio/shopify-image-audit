"""
Tests for the OAuth helper module (Sprint 19, TD-5).

Pure unit tests — the HTTP layer is mocked with ``responses``, so no
network calls leave the test process.
"""

from __future__ import annotations

import secrets

import pytest
import responses

from integrations.shopify_oauth import (
    DEFAULT_SCOPES,
    build_authorize_url,
    exchange_code_for_token,
    generate_state,
    validate_state,
)

# ---------------------------------------------------------------------------
# State generation / validation (CSRF nonce)
# ---------------------------------------------------------------------------


class TestGenerateState:
    def test_returns_non_empty_string(self) -> None:
        state = generate_state()
        assert isinstance(state, str)
        assert len(state) >= 32  # 32 random bytes ≈ 43 base64 chars

    def test_two_calls_differ(self) -> None:
        # Statistical: collision probability for 32 bytes is ~10^-77.
        a, b = generate_state(), generate_state()
        assert a != b


class TestValidateState:
    def test_matches_returns_true(self) -> None:
        assert validate_state("abc123", "abc123") is True

    def test_mismatch_returns_false(self) -> None:
        assert validate_state("abc123", "xyz789") is False

    def test_different_lengths_return_false(self) -> None:
        assert validate_state("short", "longer-string") is False

    def test_empty_strings_compare_equal(self) -> None:
        # Boundary case — empty state is rejected upstream by the
        # callback handler (returns 400), but the helper itself does
        # not raise.
        assert validate_state("", "") is True


# ---------------------------------------------------------------------------
# build_authorize_url
# ---------------------------------------------------------------------------


class TestBuildAuthorizeUrl:
    def test_includes_required_params(self) -> None:
        url = build_authorize_url(
            shop="mystore.myshopify.com",
            client_id="abc123",
            scopes=DEFAULT_SCOPES,
            redirect_uri="http://localhost:8765/callback",
            state="xyz789",
        )
        assert url.startswith("https://mystore.myshopify.com/admin/oauth/authorize?")
        assert "client_id=abc123" in url
        assert "scope=read_products%2Cread_themes%2Cread_shop" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fcallback" in url
        assert "state=xyz789" in url
        assert "grant_options%5B%5D=per-user" in url  # grant_options[]=per-user

    def test_rejects_empty_shop(self) -> None:
        with pytest.raises(ValueError, match="shop must not be empty"):
            build_authorize_url(
                shop="",
                client_id="x",
                scopes="read_products",
                redirect_uri="http://localhost/callback",
                state="x",
            )

    def test_rejects_shop_with_scheme(self) -> None:
        with pytest.raises(ValueError, match="no scheme"):
            build_authorize_url(
                shop="https://mystore.myshopify.com",
                client_id="x",
                scopes="read_products",
                redirect_uri="http://localhost/callback",
                state="x",
            )


# ---------------------------------------------------------------------------
# exchange_code_for_token
# ---------------------------------------------------------------------------


@responses.activate
class TestExchangeCodeForToken:
    def test_success_returns_access_token(self) -> None:
        responses.add(
            responses.POST,
            "https://mystore.myshopify.com/admin/oauth/access_token",
            json={"access_token": "shpat_abc123", "scope": "read_products"},
            status=200,
        )
        token = exchange_code_for_token(
            shop="mystore.myshopify.com",
            code="temp_code",
            client_id="client_abc",
            client_secret="shpss_xyz",
        )
        assert token == "shpat_abc123"

    def test_sends_form_encoded_post(self) -> None:
        responses.add(
            responses.POST,
            "https://mystore.myshopify.com/admin/oauth/access_token",
            json={"access_token": "shpat_x"},
            status=200,
        )
        exchange_code_for_token(
            shop="mystore.myshopify.com",
            code="c1",
            client_id="cid",
            client_secret="shpss_secret_value",
        )
        body = responses.calls[0].request.body
        # ``responses`` decodes the URL-encoded body into a string.
        assert isinstance(body, str)
        assert "client_id=cid" in body
        assert "code=c1" in body
        assert "client_secret=shpss_secret_value" in body

    def test_401_raises_runtime_error(self) -> None:
        responses.add(
            responses.POST,
            "https://mystore.myshopify.com/admin/oauth/access_token",
            json={"error": "invalid_request"},
            status=401,
        )
        with pytest.raises(RuntimeError, match="HTTP 401"):
            exchange_code_for_token(
                shop="mystore.myshopify.com",
                code="bad",
                client_id="cid",
                client_secret="shpss_x",
            )

    def test_missing_access_token_raises(self) -> None:
        responses.add(
            responses.POST,
            "https://mystore.myshopify.com/admin/oauth/access_token",
            json={"scope": "read_products"},  # no access_token
            status=200,
        )
        with pytest.raises(RuntimeError, match="access_token"):
            exchange_code_for_token(
                shop="mystore.myshopify.com",
                code="c1",
                client_id="cid",
                client_secret="shpss_x",
            )

    def test_invalid_json_raises(self) -> None:
        responses.add(
            responses.POST,
            "https://mystore.myshopify.com/admin/oauth/access_token",
            body="<html>oops</html>",
            status=200,
        )
        with pytest.raises(RuntimeError, match="invalid JSON"):
            exchange_code_for_token(
                shop="mystore.myshopify.com",
                code="c1",
                client_id="cid",
                client_secret="shpss_x",
            )

    def test_empty_shop_raises(self) -> None:
        with pytest.raises(ValueError, match="shop must not be empty"):
            exchange_code_for_token(
                shop="",
                code="c1",
                client_id="cid",
                client_secret="shpss_x",
            )

    def test_realistic_state_roundtrip(self) -> None:
        """End-to-end: state generated here + validate_state matches."""
        state = generate_state()
        responses.add(
            responses.POST,
            "https://mystore.myshopify.com/admin/oauth/access_token",
            json={"access_token": "shpat_x"},
            status=200,
        )
        # Exchange doesn't depend on state — this just confirms our
        # helpers don't accidentally clobber each other.
        exchange_code_for_token(
            shop="mystore.myshopify.com",
            code="c1",
            client_id="cid",
            client_secret=secrets.token_urlsafe(16),
        )
        # The state we generated is still valid (no shadowing).
        assert validate_state(state, state) is True
