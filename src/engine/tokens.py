"""
Persistent token store (Sprint 19 + 20).

Maps ``shop_domain`` → ``access_token`` and persists the mapping to
``$XDG_DATA_HOME/.shopify-image-audit/tokens.json`` with ``chmod 0o600``
(Windows: best-effort, no chmod).

Sprint 20 added symmetric encryption via :mod:`engine._crypto`:

- On supported platforms the Fernet key lives in the system keyring
  (macOS Keychain / Windows Credential Manager / Linux Secret
  Service). One key per install, no passphrase prompts.
- When ``$SHOPIFY_AUDIT_TOKENS_DISABLED=1`` is set (CI opt-out) we
  fall back to plaintext. ``chmod 0o600`` still applies.

Why a separate file from ``schedules.json``
------------------------------------------
Schedules are about *when* to re-audit; tokens are about *who* is being
audited. Conflating them would force token rotation to touch every
schedule entry, and it would leak tokens to anyone who only needs
schedule metadata (e.g. read-only monitoring tools). Splitting the files
lets users share schedule config without sharing credentials.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from engine._crypto import (
    InvalidToken,
    decrypt_mapping,
    encrypt_mapping,
    get_or_create_fernet_key,
    is_encryption_disabled,
)
from engine._logging import get_logger
from engine.history import _default_history_dir

_log = get_logger()

_TOKENS_FILENAME = "tokens.json"
#: Sentinel value for the on-disk format version. Bump if the layout
#: ever changes (e.g. KDF upgrade, multi-block payloads).
_FORMAT_VERSION = 1


def _is_encrypted_payload(data: object) -> bool:
    """Return True if ``data`` matches the new encrypted envelope shape."""
    return (
        isinstance(data, dict)
        and data.get("v") == _FORMAT_VERSION
        and isinstance(data.get("ct"), str)
        # One of these keys must be present for the envelope to be useful.
        and ("kdf" in data or "keyring" in data)
    )


def _is_legacy_plaintext(data: object) -> bool:
    """Return True if ``data`` matches the v0.15.0 plaintext shape.

    Legacy files are ``{shop_domain: access_token}`` dicts — all
    values are short alphanumeric strings (Shopify tokens start with
    ``shpat_`` / ``shpca_`` / ``shpss_``). We can't fully verify that
    without risking false negatives, so we just check the keys are
    strings and the values are strings.
    """
    if not isinstance(data, dict):
        return False
    if _is_encrypted_payload(data):
        return False
    return all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())


@dataclass
class TokensStore:
    """Filesystem-backed ``{shop_domain: access_token}`` mapping.

    Persists tokens to a JSON file with optional Fernet encryption
    (Sprint 20). The in-memory ``tokens`` dict is the source of truth;
    the file is just a persistence layer.

    The store transparently handles three on-disk shapes:

    1. **Encrypted envelope** (preferred, default): ``{"v": 1, "ct": …}``.
    2. **Legacy plaintext** (v0.15.0): ``{shop: token}`` dict — still
       readable for backwards compatibility.
    3. **Empty / corrupt / wrong format**: treated as ``{}``.
    """

    base_dir: Path = field(default_factory=lambda: _default_history_dir().parent)

    @property
    def path(self) -> Path:
        return self.base_dir / _TOKENS_FILENAME

    def load(self) -> dict[str, str]:
        """Return the persisted ``{shop_domain: token}`` mapping.

        Missing or unreadable file returns an empty dict; corrupt JSON
        and decryption failures log a warning and are treated as empty.
        """
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("Tokens file %s is unreadable: %s", self.path, exc)
            return {}

        # New encrypted envelope
        if _is_encrypted_payload(data):
            assert isinstance(data, dict)
            ct_b64 = data.get("ct")
            assert isinstance(ct_b64, str)
            try:
                blob = ct_b64.encode("ascii")
                key = get_or_create_fernet_key()
                return decrypt_mapping(blob, key)
            except (InvalidToken, RuntimeError) as exc:
                _log.warning(
                    "Tokens file %s could not be decrypted: %s. "
                    "If you lost the keyring entry, re-run "
                    "`audit shopify login <store>` to obtain a fresh token.",
                    self.path,
                    exc,
                )
                return {}

        # Legacy plaintext (Sprint 19) — still readable
        if _is_legacy_plaintext(data):
            assert isinstance(data, dict)
            return {str(k): str(v) for k, v in data.items()}

        return {}

    def save(self, tokens: dict[str, str]) -> Path:
        """Write ``tokens`` to disk with ``chmod 0o600``.

        When encryption is enabled (the default) we serialise through
        :mod:`engine._crypto`; otherwise we fall back to plaintext.
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)

        if is_encryption_disabled():
            payload: dict[str, object] = dict(tokens)
            _log.warning("$SHOPIFY_AUDIT_TOKENS_DISABLED is set; writing tokens as plaintext (still chmod 0600).")
        else:
            try:
                key = get_or_create_fernet_key()
            except RuntimeError as exc:
                # No keyring available — surface a clear error so the
                # caller can decide between setting the disable flag
                # or adding a passphrase path (not in v0.16.0).
                raise RuntimeError(
                    f"Cannot encrypt tokens: {exc}. Set $SHOPIFY_AUDIT_TOKENS_DISABLED=1 to skip encryption."
                ) from exc
            blob = encrypt_mapping(tokens, key)
            payload = {
                "v": _FORMAT_VERSION,
                "keyring": True,
                "ct": blob.decode("ascii"),
            }

        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
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
