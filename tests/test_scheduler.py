"""
Tests for ``src/engine/scheduler.py`` (Sprint 7, TD-1) — scheduled
re-audit via the external-cron model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from audit.models import AuditResult
from engine.cli import app
from engine.history import HistoryStore
from engine.scheduler import (
    ScheduleConfig,
    ScheduleStore,
    run_all_schedules,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_audit_result() -> AuditResult:
    return AuditResult.model_validate(
        {
            "meta": {
                "url": "https://mystore.myshopify.com",
                "timestamp_utc": "2026-07-31T09:00:00Z",
                "device": "mobile",
                "runs": 1,
                "tool": "lighthouse",
            },
            "vitals": {"lcp_ms": 1800.0, "cls": 0.05, "inp_ms": 120.0, "ttfb_ms": 400.0},
            "images": [
                {
                    "src": "https://cdn.example.com/hero.jpg",
                    "role": "hero",
                    "score": 80,
                    "bytes": 95_000,
                    "mime": "image/webp",
                },
            ],
            "summary": {"top_issues": []},
        }
    )


# ---------------------------------------------------------------------------
# ScheduleConfig
# ---------------------------------------------------------------------------


class TestScheduleConfig:
    def test_from_dict_minimal(self) -> None:
        cfg = ScheduleConfig.from_dict(
            {
                "shop_domain": "a.myshopify.com",
                "url": "https://a.myshopify.com",
            }
        )
        assert cfg.shop_domain == "a.myshopify.com"
        assert cfg.device == "mobile"  # default
        assert cfg.label is None
        assert cfg.access_token is None

    def test_from_dict_all_fields(self) -> None:
        cfg = ScheduleConfig.from_dict(
            {
                "shop_domain": "a.myshopify.com",
                "url": "https://a.myshopify.com",
                "device": "desktop",
                "label": "Daily 09:00",
                "access_token": "shpat_xxx",
            }
        )
        assert cfg.device == "desktop"
        assert cfg.label == "Daily 09:00"
        assert cfg.access_token == "shpat_xxx"

    def test_from_dict_missing_key(self) -> None:
        with pytest.raises(ValueError, match="Missing required key"):
            ScheduleConfig.from_dict({"url": "https://x"})

    def test_to_dict_drops_none(self) -> None:
        cfg = ScheduleConfig(shop_domain="a", url="https://a")
        d = cfg.to_dict()
        assert "label" not in d
        assert "access_token" not in d
        assert d["shop_domain"] == "a"


# ---------------------------------------------------------------------------
# ScheduleStore
# ---------------------------------------------------------------------------


class TestScheduleStore:
    def test_load_empty_when_no_file(self, tmp_path: Path) -> None:
        store = ScheduleStore(tmp_path)
        assert store.load() == []

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        store = ScheduleStore(tmp_path)
        schedules = [
            ScheduleConfig("a.myshopify.com", "https://a", label="Daily"),
            ScheduleConfig("b.myshopify.com", "https://b"),
        ]
        store.save(schedules)
        assert store.path.exists()
        loaded = store.load()
        assert len(loaded) == 2
        assert loaded[0].shop_domain == "a.myshopify.com"
        assert loaded[0].label == "Daily"

    def test_saved_file_is_private(self, tmp_path: Path) -> None:
        """schedules.json holds access tokens — must be 0600 on POSIX (TD-3)."""
        if os.name == "nt":
            pytest.skip("POSIX permission bits not applicable on Windows")
        store = ScheduleStore(tmp_path)
        store.save([ScheduleConfig("a.myshopify.com", "https://a", access_token="tok")])
        mode = store.path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_add_new(self, tmp_path: Path) -> None:
        store = ScheduleStore(tmp_path)
        store.add(ScheduleConfig("a.myshopify.com", "https://a"))
        assert len(store.load()) == 1

    def test_add_overwrites_existing(self, tmp_path: Path) -> None:
        store = ScheduleStore(tmp_path)
        store.add(ScheduleConfig("a.myshopify.com", "https://a", device="mobile"))
        store.add(ScheduleConfig("a.myshopify.com", "https://a", device="desktop"))
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].device == "desktop"

    def test_remove(self, tmp_path: Path) -> None:
        store = ScheduleStore(tmp_path)
        store.add(ScheduleConfig("a.myshopify.com", "https://a"))
        store.add(ScheduleConfig("b.myshopify.com", "https://b"))
        store.remove("a.myshopify.com")
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].shop_domain == "b.myshopify.com"

    def test_get_existing(self, tmp_path: Path) -> None:
        store = ScheduleStore(tmp_path)
        store.add(ScheduleConfig("a.myshopify.com", "https://a"))
        found = store.get("a.myshopify.com")
        assert found is not None
        assert found.url == "https://a"

    def test_get_missing(self, tmp_path: Path) -> None:
        store = ScheduleStore(tmp_path)
        assert store.get("nonexistent") is None

    def test_corrupt_file_returns_empty(self, tmp_path: Path) -> None:
        store = ScheduleStore(tmp_path)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("{not json", encoding="utf-8")
        assert store.load() == []

    def test_bad_entry_skipped(self, tmp_path: Path) -> None:
        store = ScheduleStore(tmp_path)
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text(
            json.dumps(
                [
                    {"shop_domain": "a", "url": "https://a"},
                    {"url": "missing-domain"},  # bad entry
                ]
            ),
            encoding="utf-8",
        )
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0].shop_domain == "a"


# ---------------------------------------------------------------------------
# run_all_schedules
# ---------------------------------------------------------------------------


class TestRunAllSchedules:
    def test_empty_schedules_returns_empty(self, tmp_path: Path) -> None:
        schedule_store = ScheduleStore(tmp_path / "schedules")
        history_store = HistoryStore(base_dir=tmp_path / "history")
        results = run_all_schedules(schedule_store, history_store=history_store)
        assert results == []

    def test_success_records_to_history(
        self,
        tmp_path: Path,
        sample_audit_result: AuditResult,
    ) -> None:
        schedule_store = ScheduleStore(tmp_path / "schedules")
        schedule_store.add(
            ScheduleConfig(
                "mystore.myshopify.com",
                "https://mystore.myshopify.com",
            )
        )
        history_store = HistoryStore(base_dir=tmp_path / "history")

        with patch("engine.cli_helpers._dispatchers.fetch_url_as_audit", return_value=sample_audit_result):
            results = run_all_schedules(schedule_store, history_store=history_store)

        assert len(results) == 1
        assert results[0].success
        assert results[0].entry_id is not None
        # History was recorded
        entries = history_store.list_entries("mystore.myshopify.com")
        assert len(entries) == 1

    def test_failure_does_not_abort_rest(
        self,
        tmp_path: Path,
        sample_audit_result: AuditResult,
    ) -> None:
        schedule_store = ScheduleStore(tmp_path / "schedules")
        schedule_store.add(ScheduleConfig("bad.myshopify.com", "https://bad"))
        schedule_store.add(ScheduleConfig("good.myshopify.com", "https://good"))
        history_store = HistoryStore(base_dir=tmp_path / "history")

        def fake_fetch(url, *, strategy, api_key=None):
            if "bad" in url:
                raise RuntimeError("API error")
            return sample_audit_result

        with patch("engine.cli_helpers._dispatchers.fetch_url_as_audit", side_effect=fake_fetch):
            results = run_all_schedules(schedule_store, history_store=history_store)

        assert len(results) == 2
        assert not results[0].success  # bad
        assert results[0].error == "API error"
        assert results[1].success  # good

    def test_history_record_failure_surfaces_error(
        self,
        tmp_path: Path,
        sample_audit_result: AuditResult,
    ) -> None:
        schedule_store = ScheduleStore(tmp_path / "schedules")
        schedule_store.add(
            ScheduleConfig(
                "mystore.myshopify.com",
                "https://mystore.myshopify.com",
            )
        )

        class FailingHistoryStore:
            def record(self, *args, **kwargs):
                raise OSError("disk full")

        with patch("engine.cli_helpers._dispatchers.fetch_url_as_audit", return_value=sample_audit_result):
            results = run_all_schedules(
                schedule_store,
                history_store=FailingHistoryStore(),
            )

        assert len(results) == 1
        assert not results[0].success
        assert "disk full" in (results[0].error or "")


# ---------------------------------------------------------------------------
# CLI: audit schedule
# ---------------------------------------------------------------------------


class TestScheduleCli:
    def test_unknown_subcommand_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "schedule",
                "bogus",
                "--schedule-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2

    def test_list_empty_exits_0(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "schedule",
                "list",
                "--schedule-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        assert "no schedules" in result.stdout.lower()

    def test_add_then_list(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "mystore.myshopify.com",
                "https://mystore.myshopify.com",
                "--label",
                "Daily",
                "--schedule-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        assert "Schedule added" in result.stdout

        result = runner.invoke(
            app,
            [
                "schedule",
                "list",
                "--schedule-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        assert "mystore.myshopify.com" in result.stdout

    def test_add_requires_domain_and_url(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "--schedule-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2

    def test_remove(self, tmp_path: Path) -> None:
        runner.invoke(
            app,
            [
                "schedule",
                "add",
                "a.myshopify.com",
                "https://a",
                "--schedule-dir",
                str(tmp_path),
            ],
        )
        result = runner.invoke(
            app,
            [
                "schedule",
                "remove",
                "a.myshopify.com",
                "--schedule-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        assert "removed" in result.stdout.lower()

    def test_invalid_device_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "schedule",
                "add",
                "a.myshopify.com",
                "https://a",
                "--device",
                "tablet",
                "--schedule-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2

    def test_run_all_empty_exits_0(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "schedule",
                "run-all",
                "--schedule-dir",
                str(tmp_path / "s"),
                "--history-dir",
                str(tmp_path / "h"),
            ],
        )
        assert result.exit_code == 0
        assert "no schedules" in result.stdout.lower()
