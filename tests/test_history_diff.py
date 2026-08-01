"""
Tests for ``audit history diff`` (Sprint 5, TD-4).

Covers: stable entry-ids, HistoryStore.get_by_id, compare_entries,
generate_diff_html, and the CLI subcommand with happy + error paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from audit.models import AuditResult
from engine.cli import app
from engine.history import HistoryStore, generate_diff_html

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def baseline_before() -> AuditResult:
    return AuditResult.model_validate(
        {
            "meta": {
                "url": "https://mystore.myshopify.com",
                "timestamp_utc": "2026-07-23T10:00:00Z",
                "device": "mobile",
                "runs": 1,
                "tool": "lighthouse",
            },
            "vitals": {"lcp_ms": 4200.0, "cls": 0.18, "inp_ms": 320.0, "ttfb_ms": 900.0},
            "images": [
                {
                    "src": "https://cdn.example.com/hero.jpg",
                    "role": "hero",
                    "score": 50,
                    "bytes": 1_200_000,
                    "mime": "image/jpeg",
                },
            ],
            "summary": {"top_issues": ["Hero image is 1.2 MB"]},
        }
    )


@pytest.fixture
def baseline_after() -> AuditResult:
    return AuditResult.model_validate(
        {
            "meta": {
                "url": "https://mystore.myshopify.com",
                "timestamp_utc": "2026-07-30T15:00:00Z",
                "device": "mobile",
                "runs": 1,
                "tool": "lighthouse",
            },
            "vitals": {"lcp_ms": 1800.0, "cls": 0.05, "inp_ms": 120.0, "ttfb_ms": 400.0},
            "images": [
                {
                    "src": "https://cdn.example.com/hero.webp",
                    "role": "hero",
                    "score": 85,
                    "bytes": 95_000,
                    "mime": "image/webp",
                },
            ],
            "summary": {"top_issues": []},
        }
    )


@pytest.fixture
def populated_history(tmp_path: Path, baseline_before: AuditResult, baseline_after: AuditResult) -> HistoryStore:
    store = HistoryStore(base_dir=tmp_path)
    store.record(baseline_before, label="Pre-optimisation")
    store.record(baseline_after, label="Post-optimisation")
    return store


# ---------------------------------------------------------------------------
# HistoryEntry.id stability
# ---------------------------------------------------------------------------


class TestHistoryEntryId:
    def test_id_is_12_chars(self, populated_history: HistoryStore) -> None:
        entries = populated_history.list_entries("mystore.myshopify.com")
        for entry in entries:
            assert len(entry.id) == 12, f"id length wrong: {entry.id!r}"

    def test_id_is_hex(self, populated_history: HistoryStore) -> None:
        entries = populated_history.list_entries("mystore.myshopify.com")
        for entry in entries:
            assert all(c in "0123456789abcdef" for c in entry.id)

    def test_ids_are_unique(self, populated_history: HistoryStore) -> None:
        entries = populated_history.list_entries("mystore.myshopify.com")
        ids = {e.id for e in entries}
        assert len(ids) == len(entries)

    def test_id_stable_across_reloads(self, tmp_path: Path, baseline_after: AuditResult) -> None:
        """Re-reading the same snapshot file produces the same id."""
        store = HistoryStore(base_dir=tmp_path)
        store.record(baseline_after, label="x")
        e1 = store.list_entries("mystore.myshopify.com")[0]
        # Read again
        e2 = store.list_entries("mystore.myshopify.com")[0]
        assert e1.id == e2.id


# ---------------------------------------------------------------------------
# HistoryStore.get_by_id
# ---------------------------------------------------------------------------


class TestGetById:
    def test_finds_existing_entry(self, populated_history: HistoryStore) -> None:
        entries = populated_history.list_entries("mystore.myshopify.com")
        target_id = entries[0].id
        found = populated_history.get_by_id("mystore.myshopify.com", target_id)
        assert found is not None
        assert found.id == target_id

    def test_returns_none_for_unknown_id(self, populated_history: HistoryStore) -> None:
        assert populated_history.get_by_id("mystore.myshopify.com", "deadbeef0000") is None

    def test_returns_none_for_unknown_hostname(self, populated_history: HistoryStore) -> None:
        assert populated_history.get_by_id("unknown.example.com", "anything") is None


# ---------------------------------------------------------------------------
# HistoryStore.compare_entries
# ---------------------------------------------------------------------------


class TestCompareEntries:
    def test_returns_comparison_result(
        self,
        populated_history: HistoryStore,
        baseline_before: AuditResult,
        baseline_after: AuditResult,
    ) -> None:
        from audit.models import ComparisonResult

        entries = populated_history.list_entries("mystore.myshopify.com")
        id_a = entries[1].id  # older
        id_b = entries[0].id  # newer
        comp = populated_history.compare_entries("mystore.myshopify.com", id_a, id_b)
        assert isinstance(comp, ComparisonResult)
        # LCP went 4200 -> 1800 = -2400ms
        assert comp.vitals.lcp.before == 4200.0
        assert comp.vitals.lcp.after == 1800.0
        assert comp.vitals.lcp.delta == -2400.0
        assert comp.vitals.lcp.status == "improved"

    def test_returns_none_for_unknown_id(self, populated_history: HistoryStore) -> None:
        assert (
            populated_history.compare_entries(
                "mystore.myshopify.com",
                "deadbeef0000",
                "deadbeef0001",
            )
            is None
        )

    def test_returns_none_when_only_one_known(
        self,
        populated_history: HistoryStore,
        baseline_after: AuditResult,
    ) -> None:
        entries = populated_history.list_entries("mystore.myshopify.com")
        valid_id = entries[0].id
        # One valid, one unknown
        assert (
            populated_history.compare_entries(
                "mystore.myshopify.com",
                valid_id,
                "deadbeef9999",
            )
            is None
        )


# ---------------------------------------------------------------------------
# generate_diff_html
# ---------------------------------------------------------------------------


class TestGenerateDiffHtml:
    def test_renders_vital_deltas(
        self,
        populated_history: HistoryStore,
        baseline_before: AuditResult,
        baseline_after: AuditResult,
    ) -> None:
        entries = populated_history.list_entries("mystore.myshopify.com")
        comparison = populated_history.compare_entries(
            "mystore.myshopify.com",
            entries[1].id,
            entries[0].id,
        )
        html = generate_diff_html(
            "mystore.myshopify.com",
            entries[1],
            entries[0],
            comparison,
        )
        assert "Audit Diff" in html
        assert "4200ms" in html  # before
        assert "1800ms" in html  # after
        assert "improved" in html.lower()

    def test_renders_roi_estimate(
        self,
        populated_history: HistoryStore,
    ) -> None:
        entries = populated_history.list_entries("mystore.myshopify.com")
        comparison = populated_history.compare_entries(
            "mystore.myshopify.com",
            entries[1].id,
            entries[0].id,
        )
        html = generate_diff_html(
            "mystore.myshopify.com",
            entries[1],
            entries[0],
            comparison,
        )
        assert "ROI estimate" in html

    def test_renders_entry_ids(
        self,
        populated_history: HistoryStore,
    ) -> None:
        entries = populated_history.list_entries("mystore.myshopify.com")
        comparison = populated_history.compare_entries(
            "mystore.myshopify.com",
            entries[1].id,
            entries[0].id,
        )
        html = generate_diff_html(
            "mystore.myshopify.com",
            entries[1],
            entries[0],
            comparison,
        )
        # Both ids should appear in the meta block
        assert entries[0].id in html
        assert entries[1].id in html

    def test_accepts_dict_form(
        self,
        populated_history: HistoryStore,
    ) -> None:
        entries = populated_history.list_entries("mystore.myshopify.com")
        comparison = populated_history.compare_entries(
            "mystore.myshopify.com",
            entries[1].id,
            entries[0].id,
        )
        comparison_dict = comparison.model_dump()
        html = generate_diff_html(
            "mystore.myshopify.com",
            entries[1],
            entries[0],
            comparison_dict,
        )
        assert "Audit Diff" in html


# ---------------------------------------------------------------------------
# CLI: audit history diff
# ---------------------------------------------------------------------------


class TestHistoryDiffCli:
    def test_diff_writes_html_report(
        self,
        tmp_path: Path,
        populated_history: HistoryStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        entries = populated_history.list_entries("mystore.myshopify.com")
        id_a, id_b = entries[1].id, entries[0].id
        # validate_out_path requires relative path; chdir then pass basename.
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "history",
                "diff",
                "mystore.myshopify.com",
                "--from",
                id_a,
                "--to",
                id_b,
                "--history-dir",
                str(tmp_path),
                "-o",
                "diff.html",
            ],
        )
        assert result.exit_code == 0, f"Output: {result.stdout}"
        out_html = tmp_path / "diff.html"
        assert out_html.exists()
        assert "Audit Diff" in out_html.read_text()

    def test_diff_unknown_id_exits_2(
        self,
        tmp_path: Path,
        populated_history: HistoryStore,
    ) -> None:
        result = runner.invoke(
            app,
            [
                "history",
                "diff",
                "mystore.myshopify.com",
                "--from",
                "deadbeef0000",
                "--to",
                "deadbeef0001",
                "--history-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2

    def test_diff_requires_from_and_to(
        self,
        tmp_path: Path,
        populated_history: HistoryStore,
    ) -> None:
        """Missing --from/--to on a host with at least one entry exits 2."""
        result = runner.invoke(
            app,
            [
                "history",
                "diff",
                "mystore.myshopify.com",
                "--history-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 2

    def test_diff_no_entries_exits_0(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "history",
                "diff",
                "mystore.myshopify.com",
                "--from",
                "a",
                "--to",
                "b",
                "--history-dir",
                str(tmp_path),
            ],
        )
        # Empty history exits 0 with a friendly message
        assert result.exit_code == 0
        assert "no history" in result.stdout.lower()
