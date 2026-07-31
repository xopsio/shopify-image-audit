"""
Shared concurrency primitive (Sprint 8, TD-3).

Both ``src/engine/batch.py`` (``audit shopify batch --parallel``) and
``src/engine/scheduler.py`` (``audit schedule run-all``) share the same
shape: iterate over a list of workables, execute them via a callable,
return one result per item, with optional parallelism and optional
abort-on-first-error.

This module extracts the common execution into ``run_parallel`` and
serves as the single concurrency primitive for both callers.

Design choices
--------------
- **Sequential by default.** ``parallel <= 1`` means sequential. This
  matches the safe default of "no surprises for the user".
- **ThreadPoolExecutor for I/O-bound work.** Both batches are
  network-bound (Shopify / PageSpeed API), so threads are simpler and
  cheaper than processes. No async complexity.
- **Stop-on-error semantics.** When set, pending futures are cancelled.
  Already-completed results are kept.
- **Result ordering preserved.** The returned list has one entry per
  input, in the same order (slot-based placement). This matters because
  output lines up with the input order in the CLI.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

T = TypeVar("T")


def run_parallel(
    items: list[T],
    fn: Callable[[T], T],
    *,
    parallel: int = 1,
    stop_on_error: bool = False,
    cancelled_factory: Callable[[T], T] | None = None,
) -> list[T]:
    """Execute ``fn(item)`` for each item in ``items``, optionally in parallel.

    Args:
        items: Inputs to process. Empty list returns ``[]``.
        fn: Callable taking a single item and returning a single result.
            The result type is inferred (typically a result dataclass).
        parallel: Number of concurrent workers. ``1`` (default) is
            sequential; ``0`` means "all items in parallel" (capped at
            ``len(items)``). Negative values are treated as ``1``.
        stop_on_error: Abort on first failure. For sequential runs this
            means breaking out of the loop; for parallel runs the
            remaining futures are cancelled. When ``stop_on_error`` is
            set, slots that were skipped are filled by calling
            ``cancelled_factory(item)`` for the input. If
            ``cancelled_factory`` is None, skipped slots are dropped
            from the result.
        cancelled_factory: Optional callable that produces a "skipped"
            result for the input. Required when ``stop_on_error=True``
            and parallel > 1 if the caller wants length-preserving output.

    Returns:
        One result per input, in input order. The callable may raise;
        ``run_parallel`` does not catch exceptions — callers that need
        error envelopes should wrap ``fn`` itself.
    """
    if not items:
        return []

    # Sequential — worker count clamped to 1.
    if parallel <= 1:
        results: list[T] = []
        for item in items:
            result = fn(item)
            results.append(result)
            if stop_on_error:
                break
        # Sequential + stop_on_error: return only completed items.
        # (Cancelled factory is only meaningful in parallel mode where
        # some futures complete and others are cancelled.)
        return results

    # Parallel — ThreadPoolExecutor (I/O-bound workload).
    workers = min(parallel, len(items)) if parallel > 0 else len(items)
    slots: list[T | None] = [None] * len(items)
    last_completed = -1

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {
            pool.submit(fn, item): idx
            for idx, item in enumerate(items)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            slots[idx] = future.result()
            last_completed = max(last_completed, idx)
            if stop_on_error:
                # Cancel pending futures; pending slots stay None.
                for f in future_to_idx:
                    f.cancel()
                break

    # Fill skipped slots with cancelled_factory if provided; otherwise
    # drop them (sequential-style output).
    out: list[T] = []
    for idx, slot in enumerate(slots):
        if slot is not None:
            out.append(slot)
        elif stop_on_error and cancelled_factory is not None:
            out.append(cancelled_factory(items[idx]))
    return out
