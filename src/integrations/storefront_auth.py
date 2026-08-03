"""
Authenticated Lighthouse against password-protected Shopify stores (Sprint 25).

Shopify storefronts with password protection set the ``_shopify_essential``
cookie (HttpOnly, Secure, SameSite=Lax) on a successful POST to ``/password``.
We POST the password form once with ``requests``, capture the resulting
``Set-Cookie``, and hand it to Lighthouse via ``--extra-headers`` so the
audited pages render as if the user were logged in.

Limitations
-----------
- Stores with hCaptcha on the password form will fail with a clear error
  rather than be silently bypassed.
- Only the storefront-password flow is implemented; admin login, customer
  login and multi-factor flows are out of scope.
- ``_shopify_essential`` is host-only (no ``Domain`` attribute); the session
  is tied to the exact host it was obtained from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import requests

#: Name of the cookie that proves a successful storefront-password login.
#: Shopify sets this on every page; the value flips on a successful POST.
COOKIE_NAME = "_shopify_essential"

#: Form fields posted to ``/password`` on a Shopify storefront.
#: ``utf8=✓`` is the standard UTF-8 checkmark Shopify uses.
FORM_FIELDS = {
    "form_type": "storefront_password",
    "utf8": "✓",
}


@dataclass(frozen=True)
class StorefrontSession:
    """Auth state for one password-protected Shopify store.

    ``cookie_header`` is a literal ``Cookie:`` value suitable for
    Lighthouse ``--extra-headers``. ``obtained_at`` is informational
    (the cookie has a 1-year Max-Age, so expiry is not enforced here).
    """

    shop_domain: str
    cookie_header: str
    obtained_at: datetime


class StorefrontAuthError(RuntimeError):
    """Raised when storefront authentication fails.

    Sub-classes distinguish the failure mode so the CLI can pick an
    appropriate exit code and message. All subclasses map to exit 2
    (invalid args / user input) except :class:`StorefrontNetworkError`
    which keeps the connection-failure semantics.
    """

    retryable: bool = False


class StorefrontWrongPasswordError(StorefrontAuthError):
    """The submitted password was rejected (200 OK on /password)."""


class StorefrontCaptchaError(StorefrontAuthError):
    """The storefront requires solving a captcha before login."""


class StorefrontMissingCookieError(StorefrontAuthError):
    """The redirect was 302 but no _shopify_essential cookie was set."""


class StorefrontUnexpectedResponseError(StorefrontAuthError):
    """The response did not match any known pattern."""


class StorefrontNetworkError(StorefrontAuthError):
    """A network-level error prevented the request from completing."""

    retryable = True


def _cookie_header_from_response(response: requests.Response) -> str | None:
    """Extract the ``_shopify_essential`` cookie from a ``requests.Response``.

    Returns a ``Cookie:`` value string (e.g. ``_shopify_essential=abc123``)
    or ``None`` if the cookie was not set.
    """
    # ``response.headers.get("set-cookie")`` returns the raw header value
    # which may contain multiple cookies separated by ", " — but the
    # pattern "name=value;" is unambiguous for a single-cookie header.
    raw = response.headers.get("set-cookie", "")
    if not raw:
        return None
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk.startswith(COOKIE_NAME + "="):
            value = chunk.split(";", 1)[0]
            return value
    return None


def authenticate_storefront(
    shop_domain: str,
    password: str,
    *,
    timeout: float = 30.0,
    session: requests.Session | None = None,
) -> StorefrontSession:
    """POST the Shopify ``/password`` form and return the resulting session.

    Args:
        shop_domain: Bare hostname (e.g. ``visualgain.myshopify.com``).
        password: The storefront password.
        timeout: HTTP timeout in seconds (default 30).
        session: Optional ``requests.Session`` (for tests / cookie reuse).

    Returns:
        A :class:`StorefrontSession` carrying the ``Cookie:`` header value
        to pass to Lighthouse via ``--extra-headers``.

    Raises:
        StorefrontAuthError: subclasses for each failure mode.
    """
    url = f"https://{shop_domain}/password"
    data = {**FORM_FIELDS, "password": password}
    http = session or requests

    try:
        response = http.post(
            url,
            data=data,
            timeout=timeout,
            allow_redirects=False,
            headers={"User-Agent": "shopify-image-audit/0.17"},
        )
    except requests.RequestException as exc:
        raise StorefrontNetworkError(f"Network error contacting {url}: {exc}") from exc

    cookie_value = _cookie_header_from_response(response)

    # Success: 302/303 redirect with both a Location header and the auth
    # cookie. We require all three signals because Shopify also sets
    # ``_shopify_essential`` on /password GETs and on wrong-password
    # POSTs (the cookie value does NOT change). Only a true auth
    # success produces a redirect (typically to / or /?pb=0).
    if response.status_code in (302, 303) and response.headers.get("location") and cookie_value is not None:
        return StorefrontSession(
            shop_domain=shop_domain,
            cookie_header=cookie_value,
            obtained_at=datetime.now(UTC),
        )

    # Wrong password: Shopify re-renders /password with 200.
    if response.status_code == 200:
        body = response.text.lower()
        if "hcaptcha" in body or ("captcha" in body and "challenge" in body):
            raise StorefrontCaptchaError(
                f"Store {shop_domain} requires solving a captcha on the "
                f"password form. Authenticated Lighthouse cannot bypass it."
            )
        raise StorefrontWrongPasswordError(f"Wrong storefront password for {shop_domain}.")

    if response.status_code in (302, 303) and cookie_value is None:
        raise StorefrontMissingCookieError(
            f"Store {shop_domain} redirected (HTTP {response.status_code}) "
            f"but did not set the {COOKIE_NAME} cookie. The auth flow may "
            f"have changed; please report this issue."
        )

    raise StorefrontUnexpectedResponseError(
        f"Unexpected response from {url}: HTTP {response.status_code}, no auth cookie set."
    )


__all__ = [
    "COOKIE_NAME",
    "FORM_FIELDS",
    "StorefrontSession",
    "StorefrontAuthError",
    "StorefrontWrongPasswordError",
    "StorefrontCaptchaError",
    "StorefrontMissingCookieError",
    "StorefrontUnexpectedResponseError",
    "StorefrontNetworkError",
    "authenticate_storefront",
]
