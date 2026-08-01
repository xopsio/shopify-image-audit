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
