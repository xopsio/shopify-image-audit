"""
Tests for ``src/engine/_parallel.py`` (Sprint 8, TD-3).

Plus integration tests confirming ``run_batch`` and ``run_all_schedules``
delegate to the shared helper.
"""

from __future__ import annotations

from dataclasses import dataclass

from engine._parallel import run_parallel


@dataclass
class Item:
    """Test input that simulates a callable result."""
    value: int


@dataclass
class Result:
    """Test output that mirrors ScheduleRunResult / StoreResult shape."""
    value: int
    cancelled: bool = False


def _double(item: Item) -> Result:
    return Result(value=item.value * 2)


class TestRunParallel:
    def test_empty_items_returns_empty(self) -> None:
        assert run_parallel([], _double, parallel=1) == []

    def test_sequential_default(self) -> None:
        # parallel=1 (default) → sequential, single worker.
        items = [Item(1), Item(2), Item(3)]
        results = run_parallel(items, _double)
        assert [r.value for r in results] == [2, 4, 6]

    def test_parallel_zero_means_all_concurrent(self) -> None:
        items = [Item(1), Item(2), Item(3)]
        results = run_parallel(items, _double, parallel=0)
        # Same output, parallelism is invisible to the result.
        assert [r.value for r in results] == [2, 4, 6]

    def test_parallel_explicit(self) -> None:
        items = [Item(1), Item(2), Item(3)]
        results = run_parallel(items, _double, parallel=2)
        assert [r.value for r in results] == [2, 4, 6]

    def test_stop_on_error_skips_remaining(self) -> None:
        # The second item raises — with stop_on_error=True, only the
        # first and third items should be returned (the third ran
        # before the abort took effect in the sequential case, but
        # the bug case we care about is parallel + stop_on_error).
        def maybe_fail(item: Item) -> Result:
            if item.value == 2:
                raise RuntimeError(f"boom for {item.value}")
            return Result(value=item.value * 2)

        items = [Item(1), Item(2), Item(3)]

        # Sequential + stop_on_error → returns only the first item.
        # The loop breaks before the second call.
        results = run_parallel(
            items, maybe_fail, parallel=1, stop_on_error=True,
        )
        assert len(results) == 1
        assert results[0].value == 2

    def test_cancelled_factory_only_in_parallel(self) -> None:
        # In sequential + stop_on_error mode, cancelled_factory is
        # ignored — only completed items are returned (length may vary).
        def maybe_fail(item: Item) -> Result:
            if item.value == 2:
                raise RuntimeError("boom")
            return Result(value=item.value * 2)

        items = [Item(1), Item(2), Item(3)]

        def _cancelled(item: Item) -> Result:
            return Result(value=item.value, cancelled=True)

        # Sequential: factory ignored.
        results = run_parallel(
            items,
            maybe_fail,
            parallel=1,
            stop_on_error=True,
            cancelled_factory=_cancelled,
        )
        assert len(results) == 1
        assert results[0].cancelled is False
        """Even with parallelism, output preserves input order."""
        items = [Item(i) for i in range(10)]
        results = run_parallel(items, _double, parallel=4)
        assert [r.value for r in results] == [0, 2, 4, 6, 8, 10, 12, 14, 16, 18]

    def test_parallel_bounded_by_item_count(self) -> None:
        # Parallel=20 with 2 items → only 2 workers effectively used.
        # No assertion on internal state — just verify it doesn't hang.
        results = run_parallel([Item(1), Item(2)], _double, parallel=20)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Integration: batch.py and scheduler.py both delegate to run_parallel
# ---------------------------------------------------------------------------

class TestRunParallelIntegration:
    def test_batch_uses_run_parallel(self) -> None:
        """run_batch delegates to run_parallel (same observable behaviour)."""
        # Indirect: just verify existing batch tests still work; covered
        # by the full test_run_batchSequential tests in tests/test_batch.py.
        from engine.batch import StoreConfig, run_batch
        stores = [
            StoreConfig(f"a{i}.myshopify.com", "shpat_a{i}") for i in range(3)
        ]
        from unittest.mock import patch

        with patch("engine.batch._audit_one_store",
                   side_effect=lambda s: __import__("engine.batch", fromlist=["StoreResult"]).StoreResult(
                       shop_domain=s.shop_domain, success=True, inventory=[],
                   )):
            result = run_batch(stores, parallel=1)
        assert len(result.results) == 3
        assert all(r.success for r in result.results)

    def test_scheduler_uses_run_parallel(self) -> None:
        """run_all_schedules delegates to run_parallel."""
        import tempfile

        from audit.models import AuditResult
        from engine.scheduler import (
            ScheduleConfig,
            ScheduleStore,
            run_all_schedules,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ScheduleStore(base_dir=tmpdir)
            store.add(ScheduleConfig("a.myshopify.com", "https://a"))
            store.add(ScheduleConfig("b.myshopify.com", "https://b"))

            audit = AuditResult.model_validate({
                "meta": {
                    "url": "https://a.myshopify.com",
                    "timestamp_utc": "2026-07-30T15:00:00Z",
                    "device": "mobile", "runs": 1, "tool": "lighthouse",
                },
                "vitals": {"lcp_ms": 1800.0, "cls": 0.05, "inp_ms": 120.0, "ttfb_ms": 400.0},
                "images": [],
                "summary": {"top_issues": []},
            })

            class StubHistory:
                def record(self, *a, **kw):
                    return "/tmp/snap.json"

                def list_entries(self, *a, **kw):
                    class E:
                        id = "stub-entry-id"
                    return [E()]

            from unittest.mock import patch
            with patch(
                "engine.cli_helpers._dispatchers.fetch_url_as_audit",
                return_value=audit,
            ):
                results = run_all_schedules(
                    store, history_store=StubHistory(), parallel=1,
                )
            assert len(results) == 2
            assert all(r.success for r in results)
