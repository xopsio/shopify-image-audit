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
    _audit_one_store,
    merge_inventory,
    parse_stores_file,
    run_batch,
)
from engine.cli import app
from engine.tokens import TokensStore

runner = CliRunner()


@pytest.fixture
def token_store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``TokensStore`` to a tmp path without a keyring.

    Mirrors ``tokens_dir`` in tests/test_tokens.py, but also sets
    ``$SHOPIFY_AUDIT_TOKENS_DISABLED=1`` so the store round-trips
    plaintext (the CI runner has no D-Bus / Secret Service).
    """
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("SHOPIFY_AUDIT_TOKENS_DISABLED", "1")
    return tmp_path


# ---------------------------------------------------------------------------
# Stores-file parsing
# ---------------------------------------------------------------------------


class TestParseStoresFile:
    def test_valid_json_array(self, tmp_path: Path) -> None:
        path = tmp_path / "stores.json"
        path.write_text(
            json.dumps(
                [
                    {"shop_domain": "a.myshopify.com", "access_token": "shpat_a"},
                    {"shop_domain": "b.myshopify.com", "access_token": "shpat_b"},
                ]
            )
        )
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
        # Only ``shop_domain`` is required (Sprint 21); a missing
        # ``access_token`` falls back to ``TokensStore`` at audit time.
        path = tmp_path / "missing.json"
        path.write_text(
            json.dumps(
                [
                    {"access_token": "shpat_a"},  # no shop_domain
                ]
            )
        )
        with pytest.raises(ValueError, match="Missing required key 'shop_domain'"):
            parse_stores_file(path)

    def test_valid_json_array_without_tokens(self, tmp_path: Path) -> None:
        """Entries without ``access_token`` are valid (TokensStore fallback)."""
        path = tmp_path / "stores.json"
        path.write_text(json.dumps([{"shop_domain": "a.myshopify.com"}]))
        stores = parse_stores_file(path)
        assert len(stores) == 1
        assert stores[0].shop_domain == "a.myshopify.com"
        assert stores[0].access_token is None

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            parse_stores_file(tmp_path / "nonexistent.json")


# ---------------------------------------------------------------------------
# StoreConfig
# ---------------------------------------------------------------------------


class TestStoreConfig:
    def test_from_dict_minimal(self) -> None:
        cfg = StoreConfig.from_dict(
            {
                "shop_domain": "a.myshopify.com",
                "access_token": "shpat_a",
            }
        )
        assert cfg.shop_domain == "a.myshopify.com"
        assert cfg.access_token == "shpat_a"

    def test_from_dict_missing_key_raises(self) -> None:
        with pytest.raises(ValueError, match="Missing required key 'shop_domain'"):
            StoreConfig.from_dict({"access_token": "shpat_a"})

    def test_from_dict_without_access_token(self) -> None:
        cfg = StoreConfig.from_dict({"shop_domain": "a.myshopify.com"})
        assert cfg.shop_domain == "a.myshopify.com"
        assert cfg.access_token is None


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
            json={"products": [{"id": 1, "title": "T", "handle": "h", "image": {"src": "https://x/y.jpg"}}]},
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
            json={"errors": "Not found"},
            status=404,
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
            json={"errors": "fail"},
            status=500,
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
        br = BatchResult(
            results=[
                StoreResult(shop_domain="x", success=False, error="boom"),
            ]
        )
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
                shop_domain="x",
                success=True,
            )
            run_batch(stores, parallel=0)
            assert mock_audit.call_count == 2


# ---------------------------------------------------------------------------
# _audit_one_store: TokensStore fallback (Sprint 21)
# ---------------------------------------------------------------------------


class TestAuditOneStoreTokensFallback:
    @responses.activate
    def test_falls_back_to_tokens_store(self, token_store_dir: Path) -> None:
        """A store config without ``access_token`` reads it from TokensStore."""
        TokensStore().set("a.myshopify.com", "shpat_from_store")

        # Every request must carry the persisted token, proving the
        # fallback value is what actually authenticates the client.
        header = {"X-Shopify-Access-Token": "shpat_from_store"}
        for url, payload in (
            (
                "https://a.myshopify.com/admin/api/2024-10/shop.json",
                {"shop": {"name": "A", "domain": "a.myshopify.com"}},
            ),
            (
                "https://a.myshopify.com/admin/api/2024-10/products.json",
                {"products": [{"id": 1, "title": "T", "handle": "h", "image": {"src": "https://x/y.jpg"}}]},
            ),
            (
                "https://a.myshopify.com/admin/api/2024-10/themes.json",
                {"themes": [{"id": 1, "name": "main", "role": "main"}]},
            ),
            (
                "https://a.myshopify.com/admin/api/2024-10/themes/1/assets.json",
                {"assets": []},
            ),
        ):
            responses.add(
                responses.GET,
                url,
                json=payload,
                status=200,
                match=[responses.matchers.header_matcher(header)],
            )

        result = _audit_one_store(StoreConfig(shop_domain="a.myshopify.com"))
        assert result.success, result.error
        assert len(result.inventory) == 1
        assert result.inventory[0]["source"] == "product"

    def test_missing_token_returns_actionable_error(self, token_store_dir: Path) -> None:
        """No token anywhere: clear failure telling the user to log in."""
        result = _audit_one_store(StoreConfig(shop_domain="a.myshopify.com"))
        assert not result.success
        assert result.error is not None
        assert "a.myshopify.com" in result.error
        assert "audit shopify login" in result.error
        assert result.inventory == []

    @responses.activate
    def test_explicit_token_wins_over_tokens_store(self, token_store_dir: Path) -> None:
        """An explicit ``access_token`` still takes precedence."""
        TokensStore().set("a.myshopify.com", "shpat_from_store")

        header = {"X-Shopify-Access-Token": "shpat_explicit"}
        responses.add(
            responses.GET,
            "https://a.myshopify.com/admin/api/2024-10/shop.json",
            json={"shop": {"name": "A", "domain": "a.myshopify.com"}},
            status=200,
            match=[responses.matchers.header_matcher(header)],
        )
        responses.add(
            responses.GET,
            "https://a.myshopify.com/admin/api/2024-10/products.json",
            json={"products": []},
            status=200,
            match=[responses.matchers.header_matcher(header)],
        )
        responses.add(
            responses.GET,
            "https://a.myshopify.com/admin/api/2024-10/themes.json",
            json={"themes": [{"id": 1, "name": "main", "role": "main"}]},
            status=200,
            match=[responses.matchers.header_matcher(header)],
        )
        responses.add(
            responses.GET,
            "https://a.myshopify.com/admin/api/2024-10/themes/1/assets.json",
            json={"assets": []},
            status=200,
            match=[responses.matchers.header_matcher(header)],
        )

        result = _audit_one_store(StoreConfig(shop_domain="a.myshopify.com", access_token="shpat_explicit"))
        assert result.success, result.error


# ---------------------------------------------------------------------------
# merge_inventory
# ---------------------------------------------------------------------------


class TestMergeInventory:
    def test_merges_all_stores(self) -> None:
        results = [
            StoreResult(
                shop_domain="a",
                success=True,
                inventory=[
                    {"source": "product", "url": "https://x/1.jpg"},
                ],
            ),
            StoreResult(
                shop_domain="b",
                success=True,
                inventory=[
                    {"source": "product", "url": "https://x/2.jpg"},
                    {"source": "theme_asset", "url": "https://x/3.jpg"},
                ],
            ),
        ]
        merged = merge_inventory(results)
        assert len(merged) == 3

    def test_skips_failed_stores(self) -> None:
        results = [
            StoreResult(shop_domain="a", success=False, error="boom"),
            StoreResult(
                shop_domain="b",
                success=True,
                inventory=[
                    {"source": "product", "url": "https://x/1.jpg"},
                ],
            ),
        ]
        merged = merge_inventory(results)
        assert len(merged) == 1


# ---------------------------------------------------------------------------
# CLI: audit shopify batch
# ---------------------------------------------------------------------------


class TestShopifyBatchCli:
    @responses.activate
    def test_batch_happy_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
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
        stores_file.write_text(
            json.dumps(
                [
                    {"shop_domain": "a.myshopify.com", "access_token": "shpat_a"},
                    {"shop_domain": "b.myshopify.com", "access_token": "shpat_b"},
                ]
            )
        )
        output = tmp_path / "batch.json"

        # chdir to tmp_path so validate_out_path accepts the relative output
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "shopify",
                "batch",
                "--stores-file",
                "stores.json",
                "-o",
                "batch.json",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert output.exists()
        inventory = json.loads(output.read_text())
        # Both stores returned empty inventory, so 0 entries
        assert inventory == []

    def test_batch_invalid_stores_file_exits_2(
        self,
        tmp_path: Path,
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        result = runner.invoke(
            app,
            [
                "shopify",
                "batch",
                "--stores-file",
                str(bad),
            ],
        )
        assert result.exit_code == 2

    def test_batch_missing_stores_file_exits_2(self) -> None:
        result = runner.invoke(
            app,
            [
                "shopify",
                "batch",
                "--stores-file",
                "/nonexistent/stores.json",
            ],
        )
        assert result.exit_code == 2

    def test_batch_requires_stores_file_flag(self) -> None:
        result = runner.invoke(app, ["shopify", "batch"])
        assert result.exit_code == 2
        assert "--stores-file" in result.stdout.lower()

    def test_batch_negative_parallel_exits_2(self, tmp_path: Path) -> None:
        stores = tmp_path / "s.json"
        stores.write_text(
            json.dumps(
                [
                    {"shop_domain": "a.myshopify.com", "access_token": "x"},
                ]
            )
        )
        result = runner.invoke(
            app,
            [
                "shopify",
                "batch",
                "--stores-file",
                str(stores),
                "--parallel",
                "-1",
            ],
        )
        assert result.exit_code == 2

    @responses.activate
    def test_batch_all_failed_exits_10(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Two stores, both fail
        responses.add(
            responses.GET,
            "https://bad-a.myshopify.com/admin/api/2024-10/shop.json",
            json={"errors": "fail"},
            status=500,
        )
        responses.add(
            responses.GET,
            "https://bad-b.myshopify.com/admin/api/2024-10/shop.json",
            json={"errors": "fail"},
            status=500,
        )

        stores = tmp_path / "s.json"
        stores.write_text(
            json.dumps(
                [
                    {"shop_domain": "bad-a.myshopify.com", "access_token": "x"},
                    {"shop_domain": "bad-b.myshopify.com", "access_token": "x"},
                ]
            )
        )
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "shopify",
                "batch",
                "--stores-file",
                "s.json",
            ],
        )
        assert result.exit_code == 10


# ---------------------------------------------------------------------------
# Sprint 17 — on_done callback through run_batch
# ---------------------------------------------------------------------------


class TestRunBatchOnDone:
    def test_on_done_invoked_per_completed_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_batch forwards on_done to run_parallel, which fires it per store."""
        from engine.batch import StoreResult

        seen: list[str] = []

        def _fake_audit(store):
            return StoreResult(shop_domain=store.shop_domain, inventory=[])

        monkeypatch.setattr("engine.batch._audit_one_store", _fake_audit)
        stores = [
            StoreConfig.from_dict({"shop_domain": "a.example.com", "access_token": "x"}),
            StoreConfig.from_dict({"shop_domain": "b.example.com", "access_token": "y"}),
        ]

        def cb(store, result):  # noqa: ARG001
            seen.append(result.shop_domain)

        batch = run_batch(stores, parallel=1, on_done=cb)
        assert seen == ["a.example.com", "b.example.com"]
        assert len(batch.results) == 2
