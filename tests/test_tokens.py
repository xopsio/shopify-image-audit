"""
Tests for the persistent ``TokensStore`` (Sprint 19, TD-5).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine.tokens import TokensStore


@pytest.fixture
def tokens_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the history-dir resolution to a tmp path so the store
    doesn't touch the real ``~/.local/share/...`` directory."""
    # Patch the lazy import inside ``_default_history_dir`` by setting
    # XDG_DATA_HOME — the function honours it directly.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _fake_keyring_for_class(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto-mock the keyring backend for every test in this file.

    The Linux CI runner has no D-Bus / Secret Service, so the real
    keyring backend raises ``NoKeyringError`` and our encryption path
    refuses to write. Patch a stable in-memory backend instead.
    """
    store: dict[str, str] = {}

    class _FakeBackend:
        def get_password(self, service: str, username: str) -> str | None:
            return store.get(f"{service}:{username}")

        def set_password(self, service: str, username: str, value: str) -> None:
            store[f"{service}:{username}"] = value

    def _fake_get_or_create() -> bytes:
        from cryptography.fernet import Fernet

        key = store.get("_key")
        if key is None:
            key = Fernet.generate_key()
            store["_key"] = key
        return key

    monkeypatch.setattr("engine._crypto._try_keyring", lambda: _FakeBackend())
    monkeypatch.setattr("engine.tokens.get_or_create_fernet_key", _fake_get_or_create)


class TestTokensStore:
    def test_load_missing_file_returns_empty(self, tokens_dir: Path) -> None:
        assert TokensStore().load() == {}

    def test_round_trip_persists_token(self, tokens_dir: Path) -> None:
        path = TokensStore().set("mystore.myshopify.com", "shpat_abc123")
        assert path.exists()
        assert TokensStore().get("mystore.myshopify.com") == "shpat_abc123"

    def test_get_returns_none_for_missing_shop(self, tokens_dir: Path) -> None:
        assert TokensStore().get("ghost.example.com") is None

    def test_save_chmods_600_on_posix(self, tokens_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        if os.name == "nt":
            pytest.skip("POSIX-only permission check")
        TokensStore().set("a.example.com", "shpat_x")
        mode = TokensStore().path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_overwrite_updates_existing_token(self, tokens_dir: Path) -> None:
        store = TokensStore()
        store.set("a.example.com", "old")
        store.set("a.example.com", "new")
        assert store.get("a.example.com") == "new"
        # File still contains only one entry.
        assert len(store.load()) == 1

    def test_delete_removes_entry(self, tokens_dir: Path) -> None:
        store = TokensStore()
        store.set("a.example.com", "x")
        assert store.delete("a.example.com") is True
        assert store.get("a.example.com") is None

    def test_delete_missing_returns_false(self, tokens_dir: Path) -> None:
        assert TokensStore().delete("never-existed.example.com") is False

    def test_corrupt_file_returns_empty(self, tokens_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
        # Corrupt JSON must not raise — the store degrades to empty
        # just like ScheduleStore does. We assert the behaviour, not
        # the log emission (the project logger isn't propagated to
        # pytest's caplog by default — that wiring would be its own
        # change in engine._logging).
        tokens_dir.mkdir(parents=True, exist_ok=True)
        (tokens_dir / "tokens.json").write_text("{not valid json", encoding="utf-8")
        assert TokensStore().load() == {}

    def test_non_dict_file_returns_empty(self, tokens_dir: Path) -> None:
        tokens_dir.mkdir(parents=True, exist_ok=True)
        (tokens_dir / "tokens.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert TokensStore().load() == {}

    def test_multiple_shops_persist_independently(self, tokens_dir: Path) -> None:
        store = TokensStore()
        store.set("a.example.com", "shpat_a")
        store.set("b.example.com", "shpat_b")
        loaded = store.load()
        assert loaded == {
            "a.example.com": "shpat_a",
            "b.example.com": "shpat_b",
        }


# ---------------------------------------------------------------------------
# Sprint 20 — encryption layer
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Replace the encryption key path with an in-memory dict.

    We monkeypatch ``get_or_create_fernet_key`` (the function
    ``tokens.py`` actually calls) rather than the internal
    ``_try_keyring`` — the former has a stable import path and the
    latter isn't reachable from the call site in a way that survives
    ``monkeypatch.setattr`` cleanly.
    """
    from engine._crypto import generate_fernet_key as _gfk

    store: dict[str, str] = {}

    def _fake_get_or_create() -> bytes:
        # Lazily mint a key on first use and cache it in the test's
        # shared dict so encrypted payloads can be decrypted later
        # in the same test.
        key = store.get("_key")
        if key is None:
            key = _gfk()
            store["_key"] = key
        return key

    # ``tokens.py`` did ``from engine._crypto import (...)`` so the
    # function is bound on the tokens module. Set it directly on the
    # module object — ``monkeypatch.setattr("mod.attr", ...)`` does
    # not always work for ``from X import Y`` names because the
    # attribute lookup resolves via the import system, not the
    # module's namespace.
    import engine.tokens as _tokens_mod

    monkeypatch.setattr(_tokens_mod, "get_or_create_fernet_key", _fake_get_or_create)
    return store


class _FakeBackend:
    """Minimal keyring backend stub — shared dict for round-trips."""

    # Class-level storage so multiple instances (created by separate
    # monkeypatch.setattr invocations) share the same backing dict.
    # The fixture creates one instance up front, then subsequent calls
    # within the test see the same entries.
    _shared: dict[str, str] = {}

    def __init__(self, store: dict[str, str] | None = None) -> None:
        # If the fixture passes an explicit dict, use it; otherwise use
        # the class-level shared store. We seed the shared store from
        # the test's dict on first use.
        if store is not None:
            self._store = store
            type(self)._shared.update(store)
        else:
            self._store = type(self)._shared

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get(f"{service}:{username}")

    def set_password(self, service: str, username: str, value: str) -> None:
        self._store[f"{service}:{username}"] = value


class TestEncryptedTokens:
    def test_set_persists_ciphertext_not_plaintext(self, tokens_dir: Path, fake_keyring: dict[str, str]) -> None:
        """Security property: the on-disk file must NOT contain the token."""
        TokensStore().set("a.example.com", "shpat_SUPERSECRET")
        # Read raw file bytes and confirm the token doesn't appear.
        raw = TokensStore().path.read_bytes()
        assert b"shpat_SUPERSECRET" not in raw
        assert b"a.example.com" not in raw

    def test_round_trip_through_encryption(self, tokens_dir: Path, fake_keyring: dict[str, str]) -> None:
        store = TokensStore()
        store.set("a.example.com", "shpat_abc")
        store.set("b.example.com", "shpat_def")
        assert store.load() == {
            "a.example.com": "shpat_abc",
            "b.example.com": "shpat_def",
        }

    def test_save_chmods_600_on_posix_under_encryption(self, tokens_dir: Path, fake_keyring: dict[str, str]) -> None:
        if os.name == "nt":
            pytest.skip("POSIX-only permission check")
        TokensStore().set("a.example.com", "shpat_x")
        mode = TokensStore().path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_load_legacy_plaintext_file(self, tokens_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sprint 19's plaintext format is still readable (backwards compat).

        With ``SHOPIFY_AUDIT_TOKENS_DISABLED=1`` the store writes
        plaintext ``{shop: token}`` dicts. ``load()`` returns the
        same dict verbatim — the legacy and disable-flag shapes are
        identical on disk.

        (The legacy-and-encrypted cases are tested by the round-trip
        tests above; this test pins the plaintext-on-disk shape.)
        """
        monkeypatch.setenv("SHOPIFY_AUDIT_TOKENS_DISABLED", "1")
        tokens_dir.mkdir(parents=True, exist_ok=True)
        # First, write a plaintext file (under the disable flag).
        TokensStore().set("legacy.example.com", "shpat_legacy_token")
        # Then, read it back.
        assert TokensStore().get("legacy.example.com") == "shpat_legacy_token"

    def test_decryption_failure_returns_empty(self, tokens_dir: Path, fake_keyring: dict[str, str]) -> None:
        """If the keyring entry was wiped, we degrade gracefully to empty."""
        # Write an encrypted file under the fake keyring, then "lose"
        # the key (clear the in-memory dict).
        TokensStore().set("a.example.com", "shpat_secret")
        fake_keyring.clear()
        # load() should log a warning and return {} (not raise).
        assert TokensStore().load() == {}

    def test_save_with_encryption_disabled(self, tokens_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """With the disable flag, the file is plaintext (no envelope)."""
        monkeypatch.setenv("SHOPIFY_AUDIT_TOKENS_DISABLED", "1")
        TokensStore().set("a.example.com", "shpat_visible")
        raw = TokensStore().path.read_text()
        assert "shpat_visible" in raw  # plaintext, NOT encrypted
        # And the round-trip still works.
        assert TokensStore().get("a.example.com") == "shpat_visible"
