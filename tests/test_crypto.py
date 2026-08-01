"""
Tests for the Fernet-based token encryption helpers (Sprint 20).

We mock the keyring backend entirely so the tests don't depend on a
real keyring service (CI runners have no macOS Keychain, no Windows
Credential Manager, and usually no Linux Secret Service).
"""

from __future__ import annotations

import pytest

from engine import _crypto
from engine._crypto import (
    decrypt_mapping,
    derive_key_from_passphrase,
    encrypt_mapping,
    generate_fernet_key,
    is_encryption_disabled,
    make_salt,
)

# ---------------------------------------------------------------------------
# generate_fernet_key
# ---------------------------------------------------------------------------


class TestGenerateFernetKey:
    def test_returns_44_urlsafe_chars(self) -> None:
        # ``Fernet.generate_key`` produces 32 random bytes → 44
        # url-safe base64 characters (no padding).
        key = generate_fernet_key()
        assert isinstance(key, bytes)
        assert len(key) == 44
        assert key.endswith(b"=")  # urlsafe base64 includes padding

    def test_two_keys_differ(self) -> None:
        assert generate_fernet_key() != generate_fernet_key()


# ---------------------------------------------------------------------------
# make_salt + derive_key_from_passphrase
# ---------------------------------------------------------------------------


class TestSalt:
    def test_salt_is_16_bytes(self) -> None:
        assert len(make_salt()) == 16

    def test_two_salts_differ(self) -> None:
        assert make_salt() != make_salt()


class TestDeriveKeyFromPassphrase:
    def test_returns_32_bytes(self) -> None:
        salt = make_salt()
        key = derive_key_from_passphrase("correct horse battery staple", salt)
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_same_passphrase_same_key(self) -> None:
        salt = make_salt()
        a = derive_key_from_passphrase("same passphrase", salt)
        b = derive_key_from_passphrase("same passphrase", salt)
        assert a == b

    def test_different_salt_different_key(self) -> None:
        a = derive_key_from_passphrase("same passphrase", make_salt())
        b = derive_key_from_passphrase("same passphrase", make_salt())
        assert a != b

    def test_empty_passphrase_raises(self) -> None:
        with pytest.raises(ValueError, match="passphrase must not be empty"):
            derive_key_from_passphrase("", make_salt())


# ---------------------------------------------------------------------------
# encrypt_mapping / decrypt_mapping roundtrip
# ---------------------------------------------------------------------------


class TestEncryptDecryptRoundtrip:
    def test_encrypt_then_decrypt_recovers_data(self) -> None:
        key = generate_fernet_key()
        data = {"a.example.com": "shpat_abc123", "b.example.com": "shpat_def456"}
        blob = encrypt_mapping(data, key)
        assert decrypt_mapping(blob, key) == data

    def test_ciphertext_differs_from_plaintext(self) -> None:
        """Security property: encrypted blob must not contain the plaintext."""
        key = generate_fernet_key()
        blob = encrypt_mapping({"shop.myshopify.com": "shpat_SUPERSECRET"}, key)
        assert b"shpat_SUPERSECRET" not in blob
        assert b"shop.myshopify.com" not in blob

    def test_empty_dict_roundtrips(self) -> None:
        key = generate_fernet_key()
        assert decrypt_mapping(encrypt_mapping({}, key), key) == {}


class TestDecryptMappingErrors:
    def test_wrong_key_raises_invalid_token(self) -> None:
        ct = encrypt_mapping({"k": "v"}, generate_fernet_key())
        with pytest.raises(_crypto.InvalidToken):
            decrypt_mapping(ct, generate_fernet_key())

    def test_tampered_ciphertext_raises_invalid_token(self) -> None:
        key = generate_fernet_key()
        ct = encrypt_mapping({"k": "v"}, key)
        # Flip a bit somewhere in the middle of the Fernet token.
        tampered = ct[:20] + bytes([ct[20] ^ 0x01]) + ct[21:]
        with pytest.raises(_crypto.InvalidToken):
            decrypt_mapping(tampered, key)

    def test_non_dict_payload_raises_invalid_token(self) -> None:
        """A ciphertext that decrypts to a JSON array is rejected."""
        import json as _json

        from cryptography.fernet import Fernet

        key = generate_fernet_key()
        blob = Fernet(key).encrypt(_json.dumps([1, 2, 3]).encode())
        with pytest.raises(_crypto.InvalidToken, match="not a JSON object"):
            decrypt_mapping(blob, key)


# ---------------------------------------------------------------------------
# is_encryption_disabled
# ---------------------------------------------------------------------------


class TestIsEncryptionDisabled:
    def test_default_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_crypto.DISABLED_ENV_VAR, raising=False)
        assert is_encryption_disabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "Yes"])
    def test_truthy_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(_crypto.DISABLED_ENV_VAR, value)
        assert is_encryption_disabled() is True

    def test_falsy_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_crypto.DISABLED_ENV_VAR, "0")
        assert is_encryption_disabled() is False

    def test_unrelated_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_crypto.DISABLED_ENV_VAR, "maybe")
        assert is_encryption_disabled() is False
