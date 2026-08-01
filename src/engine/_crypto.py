"""
Token encryption helpers (Sprint 20).

The ``TokensStore`` persists Shopify Admin access tokens to
``tokens.json``. Plaintext is unacceptable for a credential file, even
with ``chmod 0600``: a stray ``cat`` or editor preview would expose
the token. This module wraps the on-disk format with symmetric
encryption.

Key management
--------------
1. **Primary**: store the Fernet key in the system keyring
   (``keyring`` package). macOS Keychain / Windows Credential Manager /
   Linux Secret Service — zero passphrase prompts for the user.
2. **Fallback**: derive the key from a passphrase via
   :func:`hashlib.scrypt` when no keyring backend is available
   (headless CI on Linux). The salt is generated once and stored next
   to the encrypted payload.
3. **Opt-out**: ``SHOPIFY_AUDIT_TOKENS_DISABLED=1`` skips encryption
   entirely (plaintext with ``chmod 0600``). Reserved for debugging.

Format
------
Encrypted file::

    {
      "v": 1,
      "kdf": "scrypt",
      "salt": "<base64>",
      "ct": "<base64 Fernet token>"
    }

Plaintext legacy file (still readable):::

    {"<shop_domain>": "<access_token>", ...}

The ``load()`` side detects which format the file is in and dispatches
accordingly. The ``save()`` side always writes the encrypted form (when
encryption is enabled).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets as _stdlib_secrets

from cryptography.fernet import Fernet, InvalidToken

__all__ = [
    "DISABLED_ENV_VAR",
    "Fernet",
    "InvalidToken",
    "decrypt_mapping",
    "derive_key_from_passphrase",
    "encrypt_mapping",
    "generate_fernet_key",
    "get_or_create_fernet_key",
    "is_encryption_disabled",
    "make_salt",
]

#: Keyring service name — all entries are namespaced under this so they
#: don't collide with other apps on the user's machine.
_KEYRING_SERVICE = "shopify-image-audit"
#: Keyring username for the tokens-encryption key. Single-key service,
#: so a constant username is fine.
_KEYRING_USERNAME = "tokens-encryption-key"
#: Scrypt cost factor — 2**14 (16 384) matches the OWASP recommendation
#: for interactive logins in 2024.
_SCRYPT_N = 2**14
#: Salt length in bytes for scrypt-derived keys.
_SALT_LENGTH = 16
#: Marker for the on-disk encryption format version.
_FORMAT_VERSION = 1
#: Env var to skip encryption entirely (plaintext on disk).
DISABLED_ENV_VAR = "SHOPIFY_AUDIT_TOKENS_DISABLED"


def is_encryption_disabled() -> bool:
    """Return True if the user has opted out of token encryption."""
    return os.environ.get(DISABLED_ENV_VAR, "").lower() in ("1", "true", "yes")


def _try_keyring() -> keyring.backend.KeyringBackend | None:  # type: ignore[name-defined]  # noqa: F821
    """Return the active keyring backend, or None if unavailable.

    Wrapped in try/except because some headless Linux boxes raise
    ``NoKeyringError`` at import-time (``keyring.errors.NoKeyringError``).
    """
    try:
        import keyring
    except ImportError:
        return None
    try:
        backend = keyring.get_keyring()
    except Exception:  # noqa: BLE001 — defensive: any backend-init failure
        return None
    # NullKeyring is ``keyring``'s way of saying "no real backend
    # available" (e.g. Linux without D-Bus).
    if backend is None or type(backend).__name__ == "NullKeyring":
        return None
    return backend


def _keyring_get() -> bytes | None:
    backend = _try_keyring()
    if backend is None:
        return None
    try:
        stored = backend.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:  # noqa: BLE001 — backend may raise on access errors
        return None
    if stored is None:
        return None
    return str(stored).encode("utf-8")


def _keyring_set(key: bytes) -> bool:
    backend = _try_keyring()
    if backend is None:
        return False
    try:
        backend.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key.decode("utf-8"))
    except Exception:  # noqa: BLE001 — defensive
        return False
    return True


def generate_fernet_key() -> bytes:
    """Generate a fresh Fernet key (``Fernet.generate_key``)."""
    return Fernet.generate_key()


def get_or_create_fernet_key() -> bytes:
    """Return the existing Fernet key from keyring, creating one if absent.

    Returns ``None``-equivalent (``b""``) only if both keyring lookup
    AND set fail — callers handle that as the passphrase-fallback path.
    """
    existing = _keyring_get()
    if existing is not None:
        return existing
    new_key = generate_fernet_key()
    if _keyring_set(new_key):
        return new_key
    # No keyring — caller will fall back to passphrase or plaintext.
    raise RuntimeError(
        "No keyring backend available and keyring set failed. "
        f"Set ${DISABLED_ENV_VAR}=1 to skip encryption, or supply a "
        "passphrase."
    )


def derive_key_from_passphrase(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte Fernet key from ``passphrase`` + ``salt``.

    Uses :func:`hashlib.scrypt` with cost factor ``2**14`` and a
    per-process salt. The salt is stored alongside the ciphertext, so
    the same passphrase always produces the same key (and thus the
    same ciphertext can be decrypted across restarts).
    """
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=8,
        p=1,
        dklen=32,
    )


def make_salt() -> bytes:
    """Return a fresh ``_SALT_LENGTH``-byte salt for scrypt."""
    return _stdlib_secrets.token_bytes(_SALT_LENGTH)


def encrypt_mapping(data: dict[str, str], key: bytes) -> bytes:
    """Encrypt ``data`` under ``key`` and return the Fernet token bytes."""
    payload = json.dumps(data, sort_keys=True).encode("utf-8")
    return Fernet(key).encrypt(payload)


def decrypt_mapping(blob: bytes, key: bytes) -> dict[str, str]:
    """Decrypt ``blob`` under ``key``.

    Raises:
        InvalidToken: ``key`` is wrong, the payload was tampered with,
            or the file is corrupt. The caller (``TokensStore.load``)
            catches this and returns an empty dict.
    """
    payload = Fernet(key).decrypt(blob)
    result = json.loads(payload.decode("utf-8"))
    if not isinstance(result, dict):
        raise InvalidToken("Decrypted payload is not a JSON object")
    # Coerce keys/values to str — defensive against accidental non-string writes.
    return {str(k): str(v) for k, v in result.items()}
