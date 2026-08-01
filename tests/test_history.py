"""
Unit tests for ``src/engine/history.py`` — local-filesystem audit history
store (Sprint 4, TD-4).

Covers: HistoryStore record/list/latest, HistoryEntry model, hostname
extraction, snapshot round-trip, pruning, and the trend HTML generator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audit.models import AuditResult
from engine.history import (
    _MAX_ENTRIES,
    HistoryEntry,
    HistoryStore,
    _extract_hostname,
    generate_trend_html,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_result() -> AuditResult:
    return AuditResult.model_validate(
        {
            "meta": {
                "url": "https://mystore.myshopify.com",
                "timestamp_utc": "2026-07-30T15:00:00Z",
                "device": "mobile",
                "runs": 3,
                "tool": "lighthouse",
            },
            "vitals": {"lcp_ms": 2500.0, "cls": 0.05, "inp_ms": 150.0, "ttfb_ms": 600.0},
            "images": [
                {
                    "src": "https://cdn.example.com/hero.jpg",
                    "role": "hero",
                    "score": 85,
                    "bytes": 120_000,
                    "mime": "image/jpeg",
                },
                {
                    "src": "https://cdn.example.com/thumb.png",
                    "role": "decorative",
                    "score": 95,
                    "bytes": 45_000,
                    "mime": "image/png",
                },
            ],
            "summary": {"top_issues": ["Large hero image"]},
        }
    )


@pytest.fixture
def sample_result_v2() -> AuditResult:
    """A second audit result (later timestamp, slightly different vitals)."""
    return AuditResult.model_validate(
        {
            "meta": {
                "url": "https://mystore.myshopify.com",
                "timestamp_utc": "2026-08-06T10:00:00Z",
                "device": "mobile",
                "runs": 3,
                "tool": "lighthouse",
            },
            "vitals": {"lcp_ms": 1800.0, "cls": 0.03, "inp_ms": 120.0, "ttfb_ms": 400.0},
            "images": [
                {
                    "src": "https://cdn.example.com/hero.webp",
                    "role": "hero",
                    "score": 92,
                    "bytes": 85_000,
                    "mime": "image/webp",
                },
                {
                    "src": "https://cdn.example.com/thumb.png",
                    "role": "decorative",
                    "score": 97,
                    "bytes": 45_000,
                    "mime": "image/png",
                },
            ],
            "summary": {"top_issues": []},
        }
    )


# ---------------------------------------------------------------------------
# _extract_hostname
# ---------------------------------------------------------------------------


class TestExtractHostname:
    def test_simple_url(self) -> None:
        assert _extract_hostname("https://mystore.myshopify.com") == "mystore.myshopify.com"

    def test_url_with_path(self) -> None:
        assert _extract_hostname("https://mystore.myshopify.com/products") == "mystore.myshopify.com"

    def test_trailing_slash(self) -> None:
        assert _extract_hostname("https://mystore.myshopify.com/") == "mystore.myshopify.com"

    def test_http_scheme(self) -> None:
        assert _extract_hostname("http://shop.example.com") == "shop.example.com"


# ---------------------------------------------------------------------------
# HistoryEntry model
# ---------------------------------------------------------------------------


class TestHistoryEntryModel:
    def test_minimal_fields(self) -> None:
        entry = HistoryEntry(
            hostname="mystore.myshopify.com",
            timestamp_utc="2026-07-30T15:00:00Z",
            url="https://mystore.myshopify.com",
            device="mobile",
            path="mystore.myshopify.com/2026-07-30T15-00-00Z.json",
        )
        assert entry.hostname == "mystore.myshopify.com"
        assert entry.lcp_ms == 0.0  # default
        assert entry.label is None

    def test_all_fields(self) -> None:
        entry = HistoryEntry(
            hostname="s.example.com",
            timestamp_utc="2026-07-30T15:00:00Z",
            url="https://s.example.com",
            device="desktop",
            label="Baseline",
            path="s.example.com/audit.json",
            lcp_ms=1800.0,
            cls=0.03,
            inp_ms=120.0,
            ttfb_ms=400.0,
            image_count=5,
            total_bytes=500_000,
            avg_score=85.0,
        )
        assert entry.label == "Baseline"
        assert entry.lcp_ms == 1800.0

    def test_hostname_default_empty_allowed(self) -> None:
        """hostname is not validated for min_length (empty is syntactically valid)."""
        entry = HistoryEntry(
            hostname="",
            timestamp_utc="2026-07-30T15:00:00Z",
            url="https://x.com",
            device="mobile",
            path="x.json",
        )
        assert entry.hostname == ""


# ---------------------------------------------------------------------------
# HistoryStore — record + list + latest
# ---------------------------------------------------------------------------


class TestHistoryStore:
    def test_record_creates_file(self, tmp_path: Path, sample_result: AuditResult) -> None:
        store = HistoryStore(base_dir=tmp_path)
        path = store.record(sample_result)
        assert path.exists()
        assert path.suffix == ".json"

    def test_record_returns_path(self, tmp_path: Path, sample_result: AuditResult) -> None:
        store = HistoryStore(base_dir=tmp_path)
        path = store.record(sample_result)
        assert isinstance(path, Path)
        assert path.parent.name == "mystore.myshopify.com"

    def test_record_creates_hostname_dir(self, tmp_path: Path, sample_result: AuditResult) -> None:
        store = HistoryStore(base_dir=tmp_path)
        store.record(sample_result)
        assert (tmp_path / "mystore.myshopify.com").is_dir()

    def test_list_entries_returns_sorted(
        self, tmp_path: Path, sample_result: AuditResult, sample_result_v2: AuditResult
    ) -> None:
        store = HistoryStore(base_dir=tmp_path)
        store.record(sample_result)  # older
        store.record(sample_result_v2)  # newer
        entries = store.list_entries("mystore.myshopify.com")
        assert len(entries) == 2
        # Newest first
        assert entries[0].timestamp_utc == "2026-08-06T10:00:00Z"
        assert entries[1].timestamp_utc == "2026-07-30T15:00:00Z"

    def test_list_entries_empty_for_unknown(self, tmp_path: Path) -> None:
        store = HistoryStore(base_dir=tmp_path)
        entries = store.list_entries("unknown.myshopify.com")
        assert entries == []

    def test_latest_returns_newest(
        self, tmp_path: Path, sample_result: AuditResult, sample_result_v2: AuditResult
    ) -> None:
        store = HistoryStore(base_dir=tmp_path)
        store.record(sample_result)
        store.record(sample_result_v2)
        latest = store.latest("mystore.myshopify.com")
        assert latest is not None
        assert latest.timestamp_utc == "2026-08-06T10:00:00Z"

    def test_latest_none_when_empty(self, tmp_path: Path) -> None:
        store = HistoryStore(base_dir=tmp_path)
        assert store.latest("unknown.example.com") is None

    def test_list_entries_populates_summary_fields(self, tmp_path: Path, sample_result: AuditResult) -> None:
        store = HistoryStore(base_dir=tmp_path)
        store.record(sample_result)
        entries = store.list_entries("mystore.myshopify.com")
        assert len(entries) == 1
        entry = entries[0]
        assert entry.lcp_ms == 2500.0
        assert entry.cls == 0.05
        assert entry.inp_ms == 150.0
        assert entry.ttfb_ms == 600.0
        assert entry.image_count == 2
        assert entry.total_bytes == 165_000
        assert entry.avg_score == 90.0  # (85+95)/2

    def test_preserves_url_and_device(self, tmp_path: Path, sample_result: AuditResult) -> None:
        store = HistoryStore(base_dir=tmp_path)
        store.record(sample_result)
        entry = store.list_entries("mystore.myshopify.com")[0]
        assert entry.url == "https://mystore.myshopify.com"
        assert entry.device == "mobile"

    def test_label_stored_and_retrieved(self, tmp_path: Path, sample_result: AuditResult) -> None:
        store = HistoryStore(base_dir=tmp_path)
        store.record(sample_result, label="Pre-optimisation baseline")
        entries = store.list_entries("mystore.myshopify.com")
        assert entries[0].label == "Pre-optimisation baseline"

    def test_record_without_label_has_none(self, tmp_path: Path, sample_result: AuditResult) -> None:
        store = HistoryStore(base_dir=tmp_path)
        store.record(sample_result)
        entries = store.list_entries("mystore.myshopify.com")
        assert entries[0].label is None

    def test_record_with_label_stored_in_json(self, tmp_path: Path, sample_result: AuditResult) -> None:
        store = HistoryStore(base_dir=tmp_path)
        path = store.record(sample_result, label="My Label")
        raw = json.loads(path.read_text())
        assert raw["_history_label"] == "My Label"
        assert raw["_history_hostname"] == "mystore.myshopify.com"

    def test_multiple_hostnames_isolated(self, tmp_path: Path, sample_result: AuditResult) -> None:
        store = HistoryStore(base_dir=tmp_path)
        # Record for two different hostnames
        result2 = AuditResult.model_validate(
            {
                **sample_result.model_dump(),
                "meta": {**sample_result.meta.model_dump(), "url": "https://other.example.com"},
            }
        )
        store.record(sample_result)
        store.record(result2)
        assert len(store.list_entries("mystore.myshopify.com")) == 1
        assert len(store.list_entries("other.example.com")) == 1


# ---------------------------------------------------------------------------
# load_snapshot
# ---------------------------------------------------------------------------


class TestLoadSnapshot:
    def test_roundtrip_preserves_data(self, tmp_path: Path, sample_result: AuditResult) -> None:
        store = HistoryStore(base_dir=tmp_path)
        store.record(sample_result)
        entry = store.list_entries("mystore.myshopify.com")[0]
        loaded = store.load_snapshot(entry)
        assert loaded.meta.url == sample_result.meta.url
        assert loaded.vitals.lcp_ms == sample_result.vitals.lcp_ms
        assert loaded.vitals.cls == sample_result.vitals.cls
        assert len(loaded.images) == len(sample_result.images)

    def test_load_snapshot_removes_history_keys(self, tmp_path: Path, sample_result: AuditResult) -> None:
        """Internal _history_* keys must be stripped before validation."""
        store = HistoryStore(base_dir=tmp_path)
        store.record(sample_result, label="test")
        entry = store.list_entries("mystore.myshopify.com")[0]
        loaded = store.load_snapshot(entry)
        # The loaded model must not contain extra fields (extra="forbid")
        assert loaded.meta.url == sample_result.meta.url

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        store = HistoryStore(base_dir=tmp_path)
        entry = HistoryEntry(
            hostname="x",
            timestamp_utc="2026-01-01T00:00:00Z",
            url="https://x.com",
            device="mobile",
            path="x/nonexistent.json",
        )
        with pytest.raises(FileNotFoundError):
            store.load_snapshot(entry)


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


class TestPruning:
    def test_oldest_pruned_when_over_limit(self, tmp_path: Path, sample_result: AuditResult) -> None:
        """When recording more than _MAX_ENTRIES, the oldest are removed."""
        store = HistoryStore(base_dir=tmp_path)
        # Record _MAX_ENTRIES + 5 snapshots across multiple months to keep
        # timestamps both valid ISO 8601 AND correctly sortable.
        for i in range(_MAX_ENTRIES + 5):
            month = (i // 31) + 1
            day = (i % 31) + 1
            result = AuditResult.model_validate(
                {
                    **sample_result.model_dump(),
                    "meta": {
                        **sample_result.meta.model_dump(),
                        "timestamp_utc": f"2026-{month:02d}-{day:02d}T00:00:00Z",
                    },
                }
            )
            store.record(result)
        entries = store.list_entries("mystore.myshopify.com")
        assert len(entries) == _MAX_ENTRIES  # pruned to max

    def test_pruning_keeps_newest(self, tmp_path: Path, sample_result: AuditResult) -> None:
        """After pruning, the newest entries survive."""
        store = HistoryStore(base_dir=tmp_path)
        for i in range(_MAX_ENTRIES + 5):
            month = (i // 31) + 1
            day = (i % 31) + 1
            result = AuditResult.model_validate(
                {
                    **sample_result.model_dump(),
                    "meta": {
                        **sample_result.meta.model_dump(),
                        "timestamp_utc": f"2026-{month:02d}-{day:02d}T00:00:00Z",
                    },
                }
            )
            store.record(result)
        entries = store.list_entries("mystore.myshopify.com")
        # The latest should be from the last-recorded date
        last_idx = _MAX_ENTRIES + 4  # 104
        expected_month = (last_idx // 31) + 1
        expected_day = (last_idx % 31) + 1
        assert entries[0].timestamp_utc == f"2026-{expected_month:02d}-{expected_day:02d}T00:00:00Z"


# ---------------------------------------------------------------------------
# Trend HTML generator
# ---------------------------------------------------------------------------


class TestGenerateTrendHtml:
    def test_empty_entries(self) -> None:
        html = generate_trend_html("mystore.myshopify.com", [])
        assert "Audit History" in html
        assert "mystore.myshopify.com" in html
        assert "0" in html  # zero snapshots

    def test_single_entry(self, sample_result: AuditResult) -> None:
        entry = HistoryEntry(
            hostname="mystore.myshopify.com",
            timestamp_utc=sample_result.meta.timestamp_utc,
            url=sample_result.meta.url,
            device=sample_result.meta.device,
            path="mystore.myshopify.com/2026-07-30T15-00-00Z.json",
            lcp_ms=sample_result.vitals.lcp_ms,
            cls=sample_result.vitals.cls,
            inp_ms=sample_result.vitals.inp_ms,
            ttfb_ms=sample_result.vitals.ttfb_ms,
            image_count=2,
            total_bytes=165_000,
            avg_score=90.0,
        )
        html = generate_trend_html("mystore.myshopify.com", [entry])
        assert "2500ms" in html
        assert "0.050" in html
        assert "150ms" in html
        assert "90" in html  # avg score

    def test_good_vitals_coloured_properly(self) -> None:
        """Vitals within thresholds get the 'good' CSS class."""
        entry = HistoryEntry(
            hostname="good.example.com",
            timestamp_utc="2026-07-30T15:00:00Z",
            url="https://good.example.com",
            device="mobile",
            path="good/audit.json",
            lcp_ms=1800.0,  # good: <=2500
            cls=0.05,  # good: <=0.1
            inp_ms=100.0,  # good: <=200
            ttfb_ms=400.0,  # good: <=800
            image_count=1,
            total_bytes=100_000,
            avg_score=90.0,
        )
        html = generate_trend_html("good.example.com", [entry])
        # All vitals should use the 'good' class
        assert 'class="good"' in html

    def test_poor_vitals_coloured_properly(self) -> None:
        """Vitals exceeding the poor threshold get the 'poor' CSS class."""
        entry = HistoryEntry(
            hostname="poor.example.com",
            timestamp_utc="2026-07-30T15:00:00Z",
            url="https://poor.example.com",
            device="mobile",
            path="poor/audit.json",
            lcp_ms=5000.0,  # poor: >4000
            cls=0.30,  # poor: >0.25
            inp_ms=600.0,  # poor: >500
            ttfb_ms=2000.0,  # poor: >1800
            image_count=1,
            total_bytes=100_000,
            avg_score=50.0,
        )
        html = generate_trend_html("poor.example.com", [entry])
        assert 'class="poor"' in html

    def test_label_appears_in_trend(self, sample_result: AuditResult) -> None:
        entry = HistoryEntry(
            hostname="mystore.myshopify.com",
            timestamp_utc=sample_result.meta.timestamp_utc,
            url=sample_result.meta.url,
            device=sample_result.meta.device,
            label="Baseline before optimisation",
            path="mystore.myshopify.com/audit.json",
            lcp_ms=sample_result.vitals.lcp_ms,
            cls=sample_result.vitals.cls,
            inp_ms=sample_result.vitals.inp_ms,
            ttfb_ms=sample_result.vitals.ttfb_ms,
            image_count=2,
            total_bytes=165_000,
            avg_score=90.0,
        )
        html = generate_trend_html("mystore.myshopify.com", [entry])
        assert "Baseline before optimisation" in html

    def test_contains_table_and_timeline(self) -> None:
        entries = [
            HistoryEntry(
                hostname="x.com",
                timestamp_utc="2026-01-01T00:00:00Z",
                url="https://x.com",
                device="mobile",
                path="x/1.json",
                lcp_ms=2000.0,
                cls=0.05,
                inp_ms=100.0,
                ttfb_ms=500.0,
                image_count=3,
                total_bytes=300_000,
                avg_score=80.0,
            ),
        ]
        html = generate_trend_html("x.com", entries)
        assert "Snapshot Timeline" in html
        assert "LCP" in html
        assert "CLS" in html
        assert "INP" in html
        assert "TTFB" in html


# ---------------------------------------------------------------------------
# Sprint 6 TD-1: Edge-case coverage close-out
# ---------------------------------------------------------------------------


class TestDefaultHistoryDir:
    """Cover the XDG_DATA_HOME and macOS branch of _default_history_dir()."""

    def test_xdg_data_home_used_when_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from engine.history import _default_history_dir

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        result = _default_history_dir()
        assert str(result).startswith(str(tmp_path))
        assert ".shopify-image-audit" in str(result)
        assert "history" in str(result)

    def test_no_xdg_data_home_uses_default_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When XDG_DATA_HOME is not set, fall back to home-based default."""
        from engine.history import _default_history_dir

        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        # macOS path is platform-dependent; the assertion just verifies
        # the function returns a valid path under the home directory.
        result = _default_history_dir()
        assert ".shopify-image-audit" in str(result)


class TestCorruptFile:
    """A corrupt JSON snapshot file should be skipped, not crash."""

    def test_corrupt_json_in_host_dir_skipped(self, tmp_path: Path) -> None:
        from engine.history import HistoryStore

        store = HistoryStore(base_dir=tmp_path)
        host_dir = tmp_path / "demo.myshopify.com"
        host_dir.mkdir()
        # Write a valid file alongside a corrupt one
        valid = host_dir / "2026-07-30T15-00-00Z.json"
        valid.write_text('{"meta":{}, "vitals":{}, "images":[]}', encoding="utf-8")
        corrupt = host_dir / "2026-07-29T15-00-00Z.json"
        corrupt.write_text("{this is not json", encoding="utf-8")

        entries = store.list_entries("demo.myshopify.com")
        # Corrupt file is silently skipped; only the valid one is returned
        assert len(entries) == 1
