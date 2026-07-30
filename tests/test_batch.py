"""
Tests for ``src/engine/batch.py`` (Sprint 6, TD-3) — multi-store batch
processing for the Shopify Admin API.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import responses
from typer.testing import CliRunner

from engine.batch import (
    BatchResult,
    StoreConfig,
    StoreResult,
    merge_inventory,
    parse_stores_file,
    run_batch,
)
from engine.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Stores-file parsing
# ---------------------------------------------------------------------------

class TestParseStoresFile:
    def test_valid_json_array(self, tmp_path: Path) -> None:
        path = tmp_path / "stores.json"
        path.write_text(json.dumps([
            {"shop_domain": "a.myshopify.com", "access_token": "shpat_a"},
            {"shop_domain": "b.myshopify.com", "access_token": "shpat_b"},
        ]))
        stores = parse_stores_file(path)
        assert len(stores) == 2
        assert stores[0].shop_domain == "a.myshopify.com"
        assert stores[1].access_token == "shpat_b"

    def test_invalid_json_exits_2(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_stores_file(path)

    def test_not_a_json_array(self, tmp_path: Path) -> None:
        path = tmp_path / "object.json"
        path.write_text(json.dumps({"shop_domain": "x", "access_token": "y"}))
        with pytest.raises(ValueError, match="must be a JSON array"):
            parse_stores_file(path)

    def test_missing_required_key(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.json"
        path.write_text(json.dumps([
            {"shop_domain": "a.myshopify.com"},  # no access_token
        ]))
        with pytest.raises(ValueError, match="Missing required key"):
            parse_stores_file(path)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            parse_stores_file(tmp_path / "nonexistent.json")


# ---------------------------------------------------------------------------
# StoreConfig
# ---------------------------------------------------------------------------

class TestStoreConfig:
    def test_from_dict_minimal(self) -> None:
        cfg = StoreConfig.from_dict({
            "shop_domain": "a.myshopify.com", "access_token": "shpat_a",
        })
        assert cfg.shop_domain == "a.myshopify.com"
        assert cfg.access_token == "shpat_a"

    def test_from_dict_missing_key_raises(self) -> None:
        with pytest.raises(ValueError, match="Missing required key"):
            StoreConfig.from_dict({"shop_domain": "x"})


# ---------------------------------------------------------------------------
# run_batch (sequential)
# ---------------------------------------------------------------------------

class TestRunBatchSequential:
    @responses.activate
    def test_single_store_success(self) -> None:
        responses.add(
            responses.GET,
            "https://a.myshopify.com/admin/api/2024-10/shop.json",
            json={"shop": {"name": "A", "domain": "a.myshopify.com"}},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://a.myshopify.com/admin/api/2024-10/products.json",
            json={"products": [{"id": 1, "title": "T", "handle": "h",
                              "image": {"src": "https://x/y.jpg"}}]},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://a.myshopify.com/admin/api/2024-10/themes.json",
            json={"themes": [{"id": 1, "name": "main", "role": "main"}]},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://a.myshopify.com/admin/api/2024-10/themes/1/assets.json",
            json={"assets": []},
            status=200,
        )

        stores = [StoreConfig(shop_domain="a.myshopify.com", access_token="shpat")]
        result = run_batch(stores)
        assert isinstance(result, BatchResult)
        assert len(result.results) == 1
        assert result.results[0].success
        assert len(result.results[0].inventory) == 1
        assert result.results[0].inventory[0]["shop_domain"] == "a.myshopify.com"

    def test_empty_stores_returns_empty_batch(self) -> None:
        result = run_batch([])
        assert result.results == []
        assert not result.any_success
        assert not result.all_failed  # vacuously false

    @responses.activate
    def test_failure_does_not_abort_by_default(self) -> None:
        # First store: 404 (RuntimeError)
        responses.add(
            responses.GET,
            "https://bad.myshopify.com/admin/api/2024-10/shop.json",
            json={"errors": "Not found"}, status=404,
        )
        # Second store: success
        responses.add(
            responses.GET,
            "https://good.myshopify.com/admin/api/2024-10/shop.json",
            json={"shop": {"name": "G", "domain": "good.myshopify.com"}},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://good.myshopify.com/admin/api/2024-10/products.json",
            json={"products": []},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://good.myshopify.com/admin/api/2024-10/themes.json",
            json={"themes": [{"id": 1, "name": "main", "role": "main"}]},
            status=200,
        )
        responses.add(
            responses.GET,
            "https://good.myshopify.com/admin/api/2024-10/themes/1/assets.json",
            json={"assets": []},
            status=200,
        )

        stores = [
            StoreConfig("bad.myshopify.com", "shpat_bad"),
            StoreConfig("good.myshopify.com", "shpat_good"),
        ]
        result = run_batch(stores)
        assert len(result.results) == 2
        assert not result.results[0].success
        assert result.results[1].success
        assert result.any_success
        assert not result.all_failed

    @responses.activate
    def test_stop_on_error_aborts(self) -> None:
        responses.add(
            responses.GET,
            "https://first.myshopify.com/admin/api/2024-10/shop.json",
            json={"errors": "fail"}, status=500,
        )
        # Second store should NOT be called
        stores = [
            StoreConfig("first.myshopify.com", "shpat_a"),
            StoreConfig("second.myshopify.com", "shpat_b"),
        ]
        result = run_batch(stores, stop_on_error=True)
        assert len(result.results) == 1
        assert not result.results[0].success
        assert result.all_failed

    def test_all_failed_property(self) -> None:
        br = BatchResult(results=[
            StoreResult(shop_domain="x", success=False, error="boom"),
        ])
        assert br.all_failed is True
        assert br.any_success is False


# ---------------------------------------------------------------------------
# run_batch (parallel)
# ---------------------------------------------------------------------------

class TestRunBatchParallel:
    @responses.activate
    def test_parallel_runs_all_stores(self) -> None:
        # Two stores, both succeed
        for domain in ("a.myshopify.com", "b.myshopify.com"):
            responses.add(
                responses.GET,
                f"https://{domain}/admin/api/2024-10/shop.json",
                json={"shop": {"name": domain, "domain": domain}},
                status=200,
            )
            responses.add(
                responses.GET,
                f"https://{domain}/admin/api/2024-10/products.json",
                json={"products": []},
                status=200,
            )
            responses.add(
                responses.GET,
                f"https://{domain}/admin/api/2024-10/themes.json",
                json={"themes": [{"id": 1, "name": "main", "role": "main"}]},
                status=200,
            )
            responses.add(
                responses.GET,
                f"https://{domain}/admin/api/2024-10/themes/1/assets.json",
                json={"assets": []},
                status=200,
            )

        stores = [
            StoreConfig("a.myshopify.com", "shpat_a"),
            StoreConfig("b.myshopify.com", "shpat_b"),
        ]
        result = run_batch(stores, parallel=0)
        assert len(result.results) == 2
        assert all(r.success for r in result.results)

    def test_parallel_zero_means_all_concurrent(self) -> None:
        # Verify the `0 = unlimited` contract via the function signature
        stores = [
            StoreConfig("a.myshopify.com", "shpat_a"),
            StoreConfig("b.myshopify.com", "shpat_b"),
        ]
        with patch("engine.batch._audit_one_store") as mock_audit:
            mock_audit.return_value = StoreResult(
                shop_domain="x", success=True,
            )
            run_batch(stores, parallel=0)
            assert mock_audit.call_count == 2


# ---------------------------------------------------------------------------
# merge_inventory
# ---------------------------------------------------------------------------

class TestMergeInventory:
    def test_merges_all_stores(self) -> None:
        results = [
            StoreResult(shop_domain="a", success=True, inventory=[
                {"source": "product", "url": "https://x/1.jpg"},
            ]),
            StoreResult(shop_domain="b", success=True, inventory=[
                {"source": "product", "url": "https://x/2.jpg"},
                {"source": "theme_asset", "url": "https://x/3.jpg"},
            ]),
        ]
        merged = merge_inventory(results)
        assert len(merged) == 3

    def test_skips_failed_stores(self) -> None:
        results = [
            StoreResult(shop_domain="a", success=False, error="boom"),
            StoreResult(shop_domain="b", success=True, inventory=[
                {"source": "product", "url": "https://x/1.jpg"},
            ]),
        ]
        merged = merge_inventory(results)
        assert len(merged) == 1


# ---------------------------------------------------------------------------
# CLI: audit shopify batch
# ---------------------------------------------------------------------------

class TestShopifyBatchCli:
    @responses.activate
    def test_batch_happy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for domain in ("a.myshopify.com", "b.myshopify.com"):
            responses.add(
                responses.GET,
                f"https://{domain}/admin/api/2024-10/shop.json",
                json={"shop": {"name": domain, "domain": domain}},
                status=200,
            )
            responses.add(
                responses.GET,
                f"https://{domain}/admin/api/2024-10/products.json",
                json={"products": []},
                status=200,
            )
            responses.add(
                responses.GET,
                f"https://{domain}/admin/api/2024-10/themes.json",
                json={"themes": [{"id": 1, "name": "main", "role": "main"}]},
                status=200,
            )
            responses.add(
                responses.GET,
                f"https://{domain}/admin/api/2024-10/themes/1/assets.json",
                json={"assets": []},
                status=200,
            )

        stores_file = tmp_path / "stores.json"
        stores_file.write_text(json.dumps([
            {"shop_domain": "a.myshopify.com", "access_token": "shpat_a"},
            {"shop_domain": "b.myshopify.com", "access_token": "shpat_b"},
        ]))
        output = tmp_path / "batch.json"

        # chdir to tmp_path so validate_out_path accepts the relative output
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "shopify", "batch",
            "--stores-file", "stores.json",
            "-o", "batch.json",
        ])
        assert result.exit_code == 0, result.stdout
        assert output.exists()
        inventory = json.loads(output.read_text())
        # Both stores returned empty inventory, so 0 entries
        assert inventory == []

    def test_batch_invalid_stores_file_exits_2(
        self, tmp_path: Path,
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        result = runner.invoke(app, [
            "shopify", "batch",
            "--stores-file", str(bad),
        ])
        assert result.exit_code == 2

    def test_batch_missing_stores_file_exits_2(self) -> None:
        result = runner.invoke(app, [
            "shopify", "batch",
            "--stores-file", "/nonexistent/stores.json",
        ])
        assert result.exit_code == 2

    def test_batch_requires_stores_file_flag(self) -> None:
        result = runner.invoke(app, ["shopify", "batch"])
        assert result.exit_code == 2
        assert "--stores-file" in result.stdout.lower()

    def test_batch_negative_parallel_exits_2(self, tmp_path: Path) -> None:
        stores = tmp_path / "s.json"
        stores.write_text(json.dumps([
            {"shop_domain": "a.myshopify.com", "access_token": "x"},
        ]))
        result = runner.invoke(app, [
            "shopify", "batch",
            "--stores-file", str(stores),
            "--parallel", "-1",
        ])
        assert result.exit_code == 2

    @responses.activate
    def test_batch_all_failed_exits_10(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Two stores, both fail
        responses.add(
            responses.GET,
            "https://bad-a.myshopify.com/admin/api/2024-10/shop.json",
            json={"errors": "fail"}, status=500,
        )
        responses.add(
            responses.GET,
            "https://bad-b.myshopify.com/admin/api/2024-10/shop.json",
            json={"errors": "fail"}, status=500,
        )

        stores = tmp_path / "s.json"
        stores.write_text(json.dumps([
            {"shop_domain": "bad-a.myshopify.com", "access_token": "x"},
            {"shop_domain": "bad-b.myshopify.com", "access_token": "x"},
        ]))
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, [
            "shopify", "batch",
            "--stores-file", "s.json",
        ])
        assert result.exit_code == 10
