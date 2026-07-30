"""
Multi-store batch processing (Sprint 6, TD-3).

Run an ``audit shopify inventory`` operation against a list of stores
in a single invocation. Aggregates per-store results into one JSON file
with ``shop_domain`` stamped on every entry, plus a per-store error
summary.

File format (passed via ``--stores-file``):

    [
        {"shop_domain": "store-a.myshopify.com", "access_token": "shpat_..."},
        {"shop_domain": "store-b.myshopify.com", "access_token": "shpat_..."}
    ]

The file must contain a JSON array of objects with at least
``shop_domain`` and ``access_token`` keys.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from integrations.shopify_admin import ShopifyAdminClient


@dataclass(frozen=True)
class StoreConfig:
    """One store to be audited in a batch run."""

    shop_domain: str
    access_token: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StoreConfig:
        try:
            return cls(
                shop_domain=str(data["shop_domain"]),
                access_token=str(data["access_token"]),
            )
        except KeyError as exc:
            raise ValueError(
                f"Missing required key {exc.args[0]!r} in store config entry"
            ) from exc


@dataclass
class StoreResult:
    """Outcome of one store's audit in a batch run."""

    shop_domain: str
    inventory: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    success: bool = False


@dataclass
class BatchResult:
    """Aggregated outcome of a batch run."""

    results: list[StoreResult] = field(default_factory=list)

    @property
    def any_success(self) -> bool:
        return any(r.success for r in self.results)

    @property
    def all_failed(self) -> bool:
        return bool(self.results) and not self.any_success


def parse_stores_file(path: str | Path) -> list[StoreConfig]:
    """Read and validate a ``--stores-file`` JSON.

    Raises ``ValueError`` on invalid JSON or missing required keys.
    """
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in stores file {p}: {exc}") from exc

    if not isinstance(raw, list):
        raise ValueError(
            f"Stores file must be a JSON array, got {type(raw).__name__}"
        )

    return [StoreConfig.from_dict(entry) for entry in raw]


def _audit_one_store(store: StoreConfig) -> StoreResult:
    """Run the Shopify Admin inventory call for one store."""
    client = ShopifyAdminClient(store.shop_domain, store.access_token)
    try:
        products = client.get_products()
        theme_assets = client.get_theme_assets()
    except (ValueError, RuntimeError) as exc:
        return StoreResult(
            shop_domain=store.shop_domain, success=False, error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — surface any unexpected error
        return StoreResult(
            shop_domain=store.shop_domain, success=False,
            error=f"Unexpected error: {exc}",
        )

    inventory: list[dict[str, Any]] = []
    for p in products:
        if p.get("image_url"):
            inventory.append({
                "source": "product",
                "shop_domain": store.shop_domain,
                "title": p["title"],
                "url": p["image_url"],
            })
    for a in theme_assets:
        inventory.append({
            "source": "theme_asset",
            "shop_domain": store.shop_domain,
            "theme": a["theme_name"],
            "key": a["key"],
            "url": a["url"],
        })

    return StoreResult(
        shop_domain=store.shop_domain, inventory=inventory, success=True,
    )


def run_batch(
    stores: list[StoreConfig],
    *,
    parallel: int = 1,
    stop_on_error: bool = False,
) -> BatchResult:
    """Run the inventory audit for each store in ``stores``.

    Args:
        stores: List of store configs.
        parallel: Number of concurrent workers. ``0`` means all stores
            concurrently (capped at len(stores)). ``1`` (default) is
            sequential.
        stop_on_error: If True, abort on the first failure; otherwise
            continue and report all failures.

    Returns:
        ``BatchResult`` aggregating per-store outcomes. Use
        ``.any_success`` to determine whether to exit with code 0 or 10.
    """
    if not stores:
        return BatchResult()

    if parallel <= 1:
        results: list[StoreResult] = []
        for store in stores:
            result = _audit_one_store(store)
            results.append(result)
            if stop_on_error and not result.success:
                break
        return BatchResult(results=results)

    # Parallel: ThreadPoolExecutor since Shopify API calls are I/O-bound.
    workers = min(parallel, len(stores)) if parallel > 0 else len(stores)
    results = [None] * len(stores)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_idx = {
            pool.submit(_audit_one_store, store): idx
            for idx, store in enumerate(stores)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            result = future.result()
            results[idx] = result
            if stop_on_error and not result.success:
                # Cancel pending futures; remaining slots stay None
                for f in future_to_idx:
                    f.cancel()
                break

    # Fill any cancelled slots with a placeholder failure so callers
    # don't have to handle Nones.
    final: list[StoreResult] = []
    for idx, r in enumerate(results):
        if r is None:
            final.append(StoreResult(
                shop_domain=stores[idx].shop_domain,
                success=False,
                error="Cancelled due to --stop-on-error",
            ))
        else:
            final.append(r)
    return BatchResult(results=final)


def merge_inventory(results: list[StoreResult]) -> list[dict[str, Any]]:
    """Flatten per-store inventories into one combined list."""
    merged: list[dict[str, Any]] = []
    for r in results:
        merged.extend(r.inventory)
    return merged
