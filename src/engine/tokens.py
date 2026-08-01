"""
Persistent token store (Sprint 19, TD-3).

Maps ``shop_domain`` → ``access_token`` and persists the mapping to
``$XDG_DATA_HOME/.shopify-image-audit/tokens.json`` with ``chmod 0o600``
(Windows: best-effort, no chmod).

Why a separate file from ``schedules.json``
------------------------------------------
Schedules are about *when* to re-audit; tokens are about *who* is being
audited. Conflating them would force token rotation to touch every
schedule entry, and it would leak tokens to anyone who only needs
schedule metadata (e.g. read-only monitoring tools). Splitting the files
lets users share schedule config without sharing credentials.

Security
--------
The file is plain JSON. **Token encryption is explicitly out of scope
for v0.15.0** — see ``docs/ROADMAP.md``. ``chmod 0o600`` keeps the
file readable only by the owner; if you need stronger guarantees,
file an issue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from engine._logging import get_logger
from engine.history import _default_history_dir

_log = get_logger()

_TOKENS_FILENAME = "tokens.json"


@dataclass
class TokensStore:
    """Filesystem-backed ``{shop_domain: access_token}`` mapping.

    Mirrors the ``ScheduleStore`` shape (Sprint 7): same XDG directory,
    same chmod-0o600-on-save, same graceful Windows fallback. The
    in-memory ``tokens`` dict is the source of truth; the file is just
    a persistence layer.
    """

    base_dir: Path = field(default_factory=lambda: _default_history_dir().parent)

    @property
    def path(self) -> Path:
        return self.base_dir / _TOKENS_FILENAME

    def load(self) -> dict[str, str]:
        """Return the persisted ``{shop_domain: token}`` mapping.

        Missing or unreadable file returns an empty dict; corrupt JSON
        logs a warning and is treated as empty (matches the
        ``ScheduleStore`` behaviour).
        """
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("Tokens file %s is unreadable: %s", self.path, exc)
            return {}
        if not isinstance(data, dict):
            return {}
        # Coerce values to str — defensive against accidental non-string
        # writes (e.g. from a corrupt backup).
        return {str(k): str(v) for k, v in data.items()}

    def save(self, tokens: dict[str, str]) -> Path:
        """Write ``tokens`` to disk and chmod 0o600 on POSIX."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError as exc:
            _log.warning(
                "Could not set 0600 permissions on %s: %s — the file may "
                "be readable by other users. Run `chmod 600 %s` manually.",
                self.path,
                exc,
                self.path,
            )
        return self.path

    def get(self, shop_domain: str) -> str | None:
        """Return the persisted token for ``shop_domain``, or ``None``."""
        return self.load().get(shop_domain)

    def set(self, shop_domain: str, token: str) -> Path:
        """Persist ``token`` for ``shop_domain`` and return the file path."""
        tokens = self.load()
        tokens[shop_domain] = token
        return self.save(tokens)

    def delete(self, shop_domain: str) -> bool:
        """Remove a token entry. Returns ``True`` if it existed."""
        tokens = self.load()
        if shop_domain not in tokens:
            return False
        del tokens[shop_domain]
        self.save(tokens)
        return True
