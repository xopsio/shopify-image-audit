"""
Tiny embedded HTTP server that captures the OAuth redirect (Sprint 19).

Why a custom server
-------------------
The standard OAuth authorization-code flow expects the merchant's browser
to land on a URL this tool controls. A real public-app deployment would
use a hosted callback URL, but for CLI tooling the typical pattern is
"open the user's browser to an authorize URL, listen on a local port
for the redirect, exchange the code, done". This module is the "listen
on a local port" half.

Design constraints
------------------
- **Single-shot**: the server expects exactly one callback, then it
  shuts down. Restarting for a new login is cheap.
- **Threaded**: ``ThreadingHTTPServer`` runs in a daemon thread so the
  CLI can wait for ``code`` without blocking on accept().
- **Constant-time state check**: uses ``secrets.compare_digest`` via
  :func:`integrations.shopify_oauth.validate_state`. Without it, an
  attacker who can hit the callback endpoint could time-discriminate
  state mismatches.
- **Bounded lifetime**: ``timeout`` seconds. The user's browser may
  never complete the flow; we don't want a zombie server.

Production note
---------------
This server only binds to ``localhost``. Public deployments behind a
reverse proxy would terminate TLS at the proxy and forward to this
server — see ``docs/integrations/SHOPIFY_OAUTH.md``.
"""

from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from integrations.shopify_oauth import validate_state

#: Path the OAuth callback URL is registered at. The Partner dashboard
#: must be configured with the exact same path.
CALLBACK_PATH = "/callback"

#: Port range the server tries before giving up. Picked to avoid
#: common dev-server ports (3000, 5000, 8000, 8080).
_PORT_RANGE = range(18765, 18775)


class _CallbackHandler(BaseHTTPRequestHandler):
    """Single-purpose handler that records the first valid callback.

    The handler is parameterised via class-level attributes set by
    ``OAuthCallbackServer`` before the server starts.
    """

    # Populated by ``OAuthCallbackServer.__init__`` on the subclass.
    expected_state: str = ""
    result: dict[str, str] = {}

    def do_GET(self) -> None:  # noqa: N802 — http.server API name
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404, "Not Found")
            return

        params = parse_qs(parsed.query)
        code_values = params.get("code", [])
        state_values = params.get("state", [])
        error_values = params.get("error", [])

        if error_values:
            # User denied the authorisation on Shopify's side.
            self._send_html(400, f"<h1>OAuth denied</h1><p>{error_values[0]}</p>")
            self._record(error=error_values[0])
            return

        if not code_values or not state_values:
            self._send_html(400, "<h1>Bad request</h1><p>missing code or state</p>")
            return

        # Constant-time CSRF check.
        if not validate_state(state_values[0], self.expected_state):
            self._send_html(400, "<h1>State mismatch</h1><p>possible CSRF — refusing</p>")
            return

        self._send_html(
            200,
            "<h1>✓ Authorised</h1><p>You can close this tab. The CLI is processing the token.</p>",
        )
        self._record(code=code_values[0])

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Silence the default stderr access log; tests run with a real
        # HTTP server and we don't want to spam pytest output.
        return

    def _send_html(self, status: int, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _record(self, **fields: str) -> None:
        # Only the first valid callback counts; subsequent requests are
        # ignored (the server has already started shutting down).
        if not self.result:
            self.result.update(fields)


def _bind_first_free_port() -> int:
    """Return the first available TCP port in :data:`_PORT_RANGE`.

    Uses ``bind(('', 0))`` + ``getsockname()[1]`` to let the kernel
    pick, then immediately closes — there is a small race window but it
    is acceptable for a CLI tool that fails fast if no port is free.
    """
    last_error: OSError | None = None
    for port in _PORT_RANGE:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                last_error = exc
                continue
            return port
    raise RuntimeError(
        f"No free TCP port in {_PORT_RANGE.start}-{_PORT_RANGE.stop - 1}" + (f": {last_error}" if last_error else "")
    )


class OAuthCallbackServer:
    """Embedded HTTP server that captures one OAuth redirect.

    Lifecycle::

        server = OAuthCallbackServer(state="...", timeout=60)
        server.start()
        try:
            code = server.wait_for_code()
        finally:
            server.stop()

    Or use as a context manager (preferred)::

        with OAuthCallbackServer(state="...", timeout=60) as server:
            code = server.wait_for_code()
    """

    def __init__(self, state: str, *, timeout: float = 60.0) -> None:
        self._state = state
        self._timeout = timeout
        self._port = _bind_first_free_port()
        # A per-instance dict shared between the handler and the
        # ``wait_for_code`` loop. Using a module-level mutable on
        # ``_CallbackHandler`` directly is simpler but mypy flags the
        # dynamic attribute access; this pattern keeps the annotations
        # honest and the state private.
        self._result: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        # Bind the socket eagerly so ``callback_url`` is valid before
        # ``start()`` is called (used by ``audit shopify login`` to
        # print the authorize URL before opening the browser).
        self._server: ThreadingHTTPServer = self._build_server()

    def _make_handler_cls(self) -> type[_CallbackHandler]:
        """Build a per-instance handler subclass bound to this server's state.

        Crucially the handler's ``result`` is the **same dict object**
        as ``OAuthCallbackServer._result`` — the HTTP server creates a
        new handler instance per request, so without sharing the dict
        the read in ``wait_for_code`` would never see the write.
        """
        return type(
            "ConfiguredCallbackHandler",
            (_CallbackHandler,),
            {"expected_state": self._state, "result": self._result},
        )

    def _build_server(self) -> ThreadingHTTPServer:
        """Bind the socket so ``callback_url`` is valid before ``start()`` runs."""
        return ThreadingHTTPServer(("127.0.0.1", self._port), self._make_handler_cls())

    @property
    def port(self) -> int:
        return self._port

    @property
    def callback_url(self) -> str:
        """Full callback URL — what the user must register with Shopify."""
        return f"http://localhost:{self._port}{CALLBACK_PATH}"

    def start(self) -> None:
        """Start the accept loop in a daemon thread."""
        if self._server is None:
            self._server = self._build_server()
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="oauth-callback-server",
            daemon=True,
        )
        self._thread.start()

    def wait_for_code(self) -> str | None:
        """Block until the callback arrives, the timeout elapses, or stop() is called.

        Returns:
            The authorization ``code`` query parameter, or ``None`` if
            the timeout fired or Shopify returned an ``error`` parameter
            (in which case ``last_error()`` exposes the reason).
        """
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            if self._result:
                code = self._result.get("code")
                return code
            time.sleep(0.1)
        return None

    def last_error(self) -> str | None:
        """If the user denied authorisation on Shopify's side, the reason."""
        err = self._result.get("error")
        return err

    def stop(self) -> None:
        """Shut the server down. Idempotent."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

    def __enter__(self) -> OAuthCallbackServer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
