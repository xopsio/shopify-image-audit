"""
Tests for the embedded OAuth callback HTTP server (Sprint 19, TD-5).

The server runs on a real loopback socket inside a daemon thread —
the tests use ``urllib.request`` to hit it as an actual HTTP client
would. This catches bugs that pure-mock tests miss (port binding,
thread shutdown, request parsing).
"""

from __future__ import annotations

import time
from http.client import HTTPConnection, HTTPResponse

from integrations.oauth_callback_server import (
    CALLBACK_PATH,
    OAuthCallbackServer,
)


def _hit(server: OAuthCallbackServer, query: str, timeout: float = 5.0) -> HTTPResponse:
    """Send a GET to the server's callback URL with the given query string.

    Uses ``HTTPConnection`` directly (rather than ``urlopen``) so we
    can read both success and error responses — ``urlopen`` raises on
    any 4xx which makes it impossible to assert on the failure path.
    """
    # urlopen / HTTPConnection need the host:port pair.
    parsed_url = server.callback_url.replace("http://", "")
    host_port, _, _ = parsed_url.partition("/")
    host, _, port = host_port.partition(":")
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            conn = HTTPConnection(host, int(port), timeout=2.0)
            try:
                conn.request("GET", f"/{CALLBACK_PATH}?{query}")
                return conn.getresponse()
            finally:
                conn.close()
        except (ConnectionRefusedError, OSError) as exc:
            last_exc = exc
            time.sleep(0.05)
    raise RuntimeError(f"server {server.callback_url} never accepted a connection within {timeout}s: {last_exc}")


class TestCallbackServer:
    def test_serves_correct_path_with_matching_state(self) -> None:
        state = secrets_urlsafe(16)
        with OAuthCallbackServer(state, timeout=5.0) as server:
            resp = _hit(server, f"code=shpat_test&state={state}")
            assert resp.status == 200
            assert b"Authorised" in resp.read()
            code = server.wait_for_code()
            assert code == "shpat_test"

    def test_rejects_wrong_state_with_constant_time_check(self) -> None:
        # CSRF: a different state must NOT yield a code.
        state = secrets_urlsafe(16)
        with OAuthCallbackServer(state, timeout=5.0) as server:
            resp = _hit(server, "code=evil&state=attacker_state")
            assert resp.status == 400
            assert server.wait_for_code() is None

    def test_rejects_missing_code_or_state(self) -> None:
        state = secrets_urlsafe(16)
        with OAuthCallbackServer(state, timeout=5.0) as server:
            resp = _hit(server, "")
            assert resp.status == 400

    def test_records_oauth_error_parameter(self) -> None:
        state = secrets_urlsafe(16)
        with OAuthCallbackServer(state, timeout=5.0) as server:
            resp = _hit(server, f"error=access_denied&state={state}")
            assert resp.status == 400
            # The handler records the error in ``self.result`` before it
            # returns the HTTP response — but on a busy CI the dispatch
            # thread might still be cleaning up. Poll briefly so we
            # don't have a flaky race against ``last_error()``.
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and server.last_error() is None:
                time.sleep(0.02)
            assert server.last_error() == "access_denied"

    def test_timeout_returns_none(self) -> None:
        """wait_for_code must respect the timeout and not hang forever."""
        with OAuthCallbackServer("some_state", timeout=0.3) as server:
            start = time.monotonic()
            code = server.wait_for_code()
            elapsed = time.monotonic() - start
            assert code is None
            assert 0.2 <= elapsed < 1.0

    def test_stop_is_idempotent(self) -> None:
        server = OAuthCallbackServer("s", timeout=5.0)
        server.start()
        server.stop()
        server.stop()  # second stop must not raise


class TestCallbackUrlHelper:
    def test_callback_url_uses_loopback_and_correct_path(self) -> None:
        with OAuthCallbackServer("s", timeout=1.0) as server:
            assert "://localhost:" in server.callback_url
            assert server.callback_url.endswith(CALLBACK_PATH)


# Local helper (avoids importing ``secrets`` at module top).
def secrets_urlsafe(n: int) -> str:
    import secrets

    return secrets.token_urlsafe(n)
