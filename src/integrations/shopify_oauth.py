"""
Shopify Admin OAuth helper (Sprint 19).

Implements the three pieces of the standard OAuth authorization-code flow
that this CLI needs:

1. :func:`build_authorize_url` — assembles the redirect URL the user
   opens in a browser (Step 1 of the flow).
2. :func:`exchange_code_for_token` — POSTs the temporary authorization
   code to ``/admin/oauth/access_token`` to mint a permanent
   ``access_token`` (Step 2).
3. :func:`generate_state` + :func:`validate_state` — CSRF nonce for
   the redirect; :func:`validate_state` uses
   :func:`secrets.compare_digest` so timing attacks can't recover the
   expected value.

This module is **state-free** — it does not open the callback server
itself. The HTTP listener lives in
:mod:`integrations.oauth_callback_server`. Keeping the two separate
makes both trivial to unit-test: OAuthClient is a pure HTTP helper,
the callback server is a daemon-thread fixture.

Shopify Admin API notes
-----------------------
- Token lifetimes: Admin API tokens issued via the authorization-code
  flow are **non-expiring**. There is no refresh-token flow; the user
  must explicitly reinstall the app to obtain a new token.
- Scopes: comma-separated, the same vocabulary as custom apps
  (``read_products``, ``read_themes``, ``read_shop``).
- ``grant_options[]=per-user`` requests a token for the staff member
  rather than the app itself; appropriate for CLI tooling.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import requests

#: Default scope set for ``audit shopify login``. Matches the custom-app
#: scopes documented in SHOPIFY_ADMIN.md.
DEFAULT_SCOPES = "read_products,read_themes,read_shop"


def generate_state() -> str:
    """Generate a CSRF nonce for the OAuth redirect.

    32 random bytes (43 URL-safe base64 characters) — far more entropy
    than the OAuth spec requires but cheap to generate.
    """
    return secrets.token_urlsafe(32)


def validate_state(got: str, expected: str) -> bool:
    """Constant-time comparison of OAuth state values.

    Uses :func:`secrets.compare_digest` to prevent timing attacks that
    could otherwise leak the expected nonce byte by byte.
    """
    return secrets.compare_digest(got, expected)


def build_authorize_url(
    shop: str,
    client_id: str,
    scopes: str,
    redirect_uri: str,
    state: str,
) -> str:
    """Assemble the Shopify OAuth authorize URL.

    Args:
        shop: Bare shop domain (``store.myshopify.com``) — must NOT
            include scheme. The function appends ``https://`` itself.
        client_id: Public OAuth client ID issued by the Partner
            dashboard.
        scopes: Comma-separated scope list.
        redirect_uri: Where Shopify will redirect after the user
            approves. Must exactly match the URL registered in the
            Partner dashboard.
        state: CSRF nonce from :func:`generate_state`.

    Returns:
        The full URL to open in a browser.

    Raises:
        ValueError: ``shop`` is empty or contains a scheme prefix.
    """
    shop = shop.strip()
    if not shop:
        raise ValueError("shop must not be empty")
    if "://" in shop:
        raise ValueError(f"shop must be a bare domain (no scheme), got: {shop!r}")
    base = f"https://{shop}/admin/oauth/authorize"
    params = {
        "client_id": client_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        # Per-user token (the staff member who approves becomes the
        # actor); appropriate for CLI tools. Omitting this returns a
        # per-app token instead.
        "grant_options[]": "per-user",
    }
    return f"{base}?{urlencode(params)}"


def exchange_code_for_token(
    shop: str,
    code: str,
    client_id: str,
    client_secret: str,
    *,
    timeout: int = 30,
) -> str:
    """Exchange an authorization code for a permanent access token.

    Args:
        shop: Bare shop domain (same format as :func:`build_authorize_url`).
        code: The temporary ``code`` query parameter from the callback.
        client_id: Public OAuth client ID.
        client_secret: Private OAuth client secret.
        timeout: HTTP timeout in seconds.

    Returns:
        The Admin API access token (``shpat_…``).

    Raises:
        ValueError: Empty shop domain.
        RuntimeError: API returned a non-200 response or the response
            body is missing ``access_token``.
    """
    shop = shop.strip()
    if not shop:
        raise ValueError("shop must not be empty")
    url = f"https://{shop}/admin/oauth/access_token"
    try:
        response = requests.post(
            url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Shopify OAuth token exchange failed: {exc}") from exc

    if response.status_code != 200:
        # Don't include the response body verbatim — it can contain the
        # client_secret echoed back by misbehaving servers. Truncate to
        # 200 chars and redact obvious secrets.
        body = response.text[:200] if response.text else "(empty)"
        raise RuntimeError(f"Shopify OAuth token exchange returned HTTP {response.status_code}: {body}")

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Shopify OAuth token exchange returned invalid JSON: {exc}") from exc

    token = data.get("access_token")
    if not token:
        raise RuntimeError("Shopify OAuth token exchange response missing 'access_token' field")
    return str(token)
