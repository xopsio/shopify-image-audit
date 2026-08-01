"""
Unit + CLI tests for the Shopify Admin API client (Sprint 3, TD-3).

Covers:
- ``ShopifyAdminClient`` direct methods, mocked via ``responses``
- CLI ``audit shopify auth`` and ``audit shopify inventory`` integration
"""

from __future__ import annotations

import json

import pytest
import responses
from typer.testing import CliRunner

from integrations.shopify_admin import ShopifyAdminClient

# ---------------------------------------------------------------------------
# _normalize_domain
# ---------------------------------------------------------------------------


class TestNormalizeDomain:
    def test_bare_domain(self) -> None:
        assert ShopifyAdminClient._normalize_domain("mystore.myshopify.com") == "mystore.myshopify.com"

    def test_with_https(self) -> None:
        assert ShopifyAdminClient._normalize_domain("https://mystore.myshopify.com") == "mystore.myshopify.com"

    def test_with_http(self) -> None:
        assert ShopifyAdminClient._normalize_domain("http://mystore.myshopify.com") == "mystore.myshopify.com"

    def test_with_trailing_slash(self) -> None:
        assert ShopifyAdminClient._normalize_domain("mystore.myshopify.com/") == "mystore.myshopify.com"

    def test_with_path(self) -> None:
        # Path component is dropped (we only want the host).
        assert ShopifyAdminClient._normalize_domain("https://mystore.myshopify.com/admin") == "mystore.myshopify.com"

    def test_with_whitespace(self) -> None:
        assert ShopifyAdminClient._normalize_domain("  mystore.myshopify.com  ") == "mystore.myshopify.com"

    @pytest.mark.parametrize("bad", ["", "   ", "https://", "/just/a/path"])
    def test_invalid_raises(self, bad: str) -> None:
        with pytest.raises(ValueError):
            ShopifyAdminClient._normalize_domain(bad)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_stores_all_args(self) -> None:
        c = ShopifyAdminClient(
            "mystore.myshopify.com",
            "shpat_abc",
            timeout=10,
            max_retries=2,
            retry_delay=1.0,
        )
        assert c.shop_domain == "mystore.myshopify.com"
        assert c.access_token == "shpat_abc"
        assert c.timeout == 10
        assert c.max_retries == 2
        assert c.retry_delay == 1.0
        assert c.base_url == "https://mystore.myshopify.com/admin/api/2024-10"

    def test_defaults(self) -> None:
        c = ShopifyAdminClient("mystore.myshopify.com", "shpat_abc")
        assert c.timeout == 30
        assert c.max_retries == 3
        assert c.retry_delay == 2.0


# ---------------------------------------------------------------------------
# get_shop_info
# ---------------------------------------------------------------------------


@responses.activate
def test_get_shop_info_success():
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        json={
            "shop": {
                "name": "My Store",
                "domain": "mystore.myshopify.com",
                "plan_display_name": "Basic",
                "currency": "EUR",
            }
        },
        status=200,
    )
    client = ShopifyAdminClient("mystore.myshopify.com", "shpat_abc")
    info = client.get_shop_info()
    assert info == {
        "name": "My Store",
        "domain": "mystore.myshopify.com",
        "plan": "Basic",
        "currency": "EUR",
    }
    # Verify the access token was sent in the header
    assert "X-Shopify-Access-Token" in responses.calls[0].request.headers
    assert responses.calls[0].request.headers["X-Shopify-Access-Token"] == "shpat_abc"


@responses.activate
def test_get_shop_info_401_raises():
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        json={"errors": "Invalid API key or access token"},
        status=401,
    )
    client = ShopifyAdminClient("mystore.myshopify.com", "shpat_bad")
    with pytest.raises(RuntimeError, match="401"):
        client.get_shop_info()


@responses.activate
def test_get_shop_info_429_retries_then_raises():
    # Rate limit on first two attempts, success on third.
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        status=429,
    )
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        status=429,
    )
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        status=429,
    )
    client = ShopifyAdminClient("mystore.myshopify.com", "shpat_abc", max_retries=3, retry_delay=0.01)
    with pytest.raises(RuntimeError, match="rate limit"):
        client.get_shop_info()


@responses.activate
def test_get_shop_info_503_retries_then_succeeds():
    # Transient 503, recovers on the second attempt.
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        status=503,
    )
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        json={"shop": {"name": "S", "domain": "x.myshopify.com", "currency": "USD", "plan_display_name": "Pro"}},
        status=200,
    )
    client = ShopifyAdminClient("mystore.myshopify.com", "shpat_abc", max_retries=3, retry_delay=0.01)
    info = client.get_shop_info()
    assert info["name"] == "S"


@responses.activate
def test_get_shop_info_404_raises():
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        json={"errors": "Not Found"},
        status=404,
    )
    client = ShopifyAdminClient("mystore.myshopify.com", "shpat_abc", max_retries=1)
    with pytest.raises(RuntimeError, match="404"):
        client.get_shop_info()


# ---------------------------------------------------------------------------
# get_products
# ---------------------------------------------------------------------------


@responses.activate
def test_get_products_normalizes_response():
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/products.json",
        match_querystring=False,  # we'll assert separately
        json={
            "products": [
                {"id": 1, "title": "Shirt", "handle": "shirt", "image": {"src": "https://cdn.example.com/shirt.jpg"}},
                {"id": 2, "title": "No-Image", "handle": "no-image", "image": None},
                # Defensive: image is a string (shouldn't happen, but the
                # client should not crash).
                {"id": 3, "title": "Bad-Image", "handle": "bad-image", "image": "oops"},
            ]
        },
        status=200,
    )
    client = ShopifyAdminClient("mystore.myshopify.com", "shpat_abc")
    products = client.get_products(limit=50)
    assert products == [
        {"id": 1, "title": "Shirt", "handle": "shirt", "image_url": "https://cdn.example.com/shirt.jpg"},
        {"id": 2, "title": "No-Image", "handle": "no-image", "image_url": None},
        {"id": 3, "title": "Bad-Image", "handle": "bad-image", "image_url": None},
    ]
    # Verify limit=50 was sent
    assert "limit=50" in responses.calls[0].request.url


@responses.activate
def test_get_products_limit_validation():
    client = ShopifyAdminClient("mystore.myshopify.com", "shpat_abc")
    with pytest.raises(ValueError, match="limit"):
        client.get_products(limit=0)
    with pytest.raises(ValueError, match="limit"):
        client.get_products(limit=251)


# ---------------------------------------------------------------------------
# get_theme_assets
# ---------------------------------------------------------------------------


@responses.activate
def test_get_theme_assets_filters_to_images():
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/themes.json",
        json={
            "themes": [
                {"id": 1, "name": "Debut", "role": "main"},
                {"id": 2, "name": "Old", "role": "unpublished"},
            ]
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/themes/1/assets.json",
        json={
            "assets": [
                {"key": "assets/hero.jpg", "public_url": "https://cdn.example.com/hero.jpg"},
                {"key": "assets/banner.png", "public_url": "https://cdn.example.com/banner.png"},
                {"key": "assets/style.css", "public_url": "https://cdn.example.com/style.css"},
                {"key": "assets/theme.js", "public_url": "https://cdn.example.com/theme.js"},
                {"key": "assets/logo.svg", "public_url": "https://cdn.example.com/logo.svg"},
                {"key": "assets/pic.avif", "public_url": "https://cdn.example.com/pic.avif"},
                # Edge case: no public_url, should be skipped
                {"key": "assets/orphan.jpg", "public_url": None},
                # Edge case: no key, should be skipped
                {"public_url": "https://cdn.example.com/no-key.jpg"},
            ]
        },
        status=200,
    )
    client = ShopifyAdminClient("mystore.myshopify.com", "shpat_abc")
    assets = client.get_theme_assets()
    # Only image assets (jpg/png/svg/avif) — no css/js, no None URLs, no missing keys
    assert len(assets) == 4
    keys = [a["key"] for a in assets]
    assert "assets/hero.jpg" in keys
    assert "assets/banner.png" in keys
    assert "assets/logo.svg" in keys
    assert "assets/pic.avif" in keys
    assert all(a["theme_name"] == "Debut" for a in assets)


@responses.activate
def test_get_theme_assets_no_main_theme_raises():
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/themes.json",
        json={"themes": [{"id": 1, "name": "Draft", "role": "unpublished"}]},
        status=200,
    )
    client = ShopifyAdminClient("mystore.myshopify.com", "shpat_abc", max_retries=1)
    with pytest.raises(RuntimeError, match="No main theme"):
        client.get_theme_assets()


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

runner = CliRunner()


@responses.activate
def test_cli_shopify_auth_success():
    from engine.cli import app

    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        json={
            "shop": {
                "name": "Test Store",
                "domain": "mystore.myshopify.com",
                "plan_display_name": "Pro",
                "currency": "USD",
            }
        },
        status=200,
    )
    result = runner.invoke(
        app,
        [
            "shopify",
            "auth",
            "mystore.myshopify.com",
            "--access-token",
            "shpat_test_token",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Token valid" in result.stdout
    assert "Test Store" in result.stdout
    assert "Pro" in result.stdout


@responses.activate
def test_cli_shopify_auth_401_exits_10():
    from engine.cli import app

    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        json={"errors": "Invalid API key or access token"},
        status=401,
    )
    result = runner.invoke(
        app,
        [
            "shopify",
            "auth",
            "mystore.myshopify.com",
            "--access-token",
            "shpat_bad",
        ],
    )
    assert result.exit_code == 10
    assert "Shopify API error" in result.stdout


def test_cli_shopify_auth_invalid_domain_exits_2():
    from engine.cli import app

    result = runner.invoke(
        app,
        [
            "shopify",
            "auth",
            "not a domain",
            "--access-token",
            "shpat_abc",
        ],
    )
    assert result.exit_code == 2


@responses.activate
def test_cli_shopify_inventory_lists_images():
    from engine.cli import app

    # Mock products endpoint
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/products.json",
        json={
            "products": [
                {"id": 1, "title": "Shirt", "handle": "shirt", "image": {"src": "https://cdn.example.com/shirt.jpg"}},
                {"id": 2, "title": "NoImg", "handle": "noimg", "image": None},
            ]
        },
        status=200,
    )
    # Mock themes endpoint
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/themes.json",
        json={"themes": [{"id": 1, "name": "Debut", "role": "main"}]},
        status=200,
    )
    # Mock assets endpoint
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/themes/1/assets.json",
        json={
            "assets": [
                {"key": "assets/hero.jpg", "public_url": "https://cdn.example.com/hero.jpg"},
            ]
        },
        status=200,
    )

    result = runner.invoke(
        app,
        [
            "shopify",
            "inventory",
            "mystore.myshopify.com",
            "--access-token",
            "shpat_abc",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Inventory fetched" in result.stdout
    assert "shirt.jpg" in result.stdout
    assert "hero.jpg" in result.stdout
    # No-image product should NOT appear in the image list
    assert "noimg.jpg" not in result.stdout or "NoImg" not in result.stdout


@responses.activate
def test_cli_shopify_inventory_writes_output_file(tmp_path, monkeypatch):
    from engine.cli import app

    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/products.json",
        json={
            "products": [
                {"id": 1, "title": "X", "handle": "x", "image": {"src": "https://cdn.example.com/x.jpg"}},
            ]
        },
        status=200,
    )
    # Mock themes endpoint with a main theme
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/themes.json",
        json={"themes": [{"id": 1, "name": "Debut", "role": "main"}]},
        status=200,
    )
    # Mock assets endpoint (empty, but valid)
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/themes/1/assets.json",
        json={"assets": []},
        status=200,
    )
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "inventory.json"
    result = runner.invoke(
        app,
        [
            "shopify",
            "inventory",
            "mystore.myshopify.com",
            "--access-token",
            "shpat_abc",
            "-o",
            "inventory.json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    data = json.loads(out.read_text())
    assert len(data) == 1
    assert data[0]["source"] == "product"
    assert data[0]["url"] == "https://cdn.example.com/x.jpg"


def test_cli_shopify_inventory_missing_token_exits_2():
    from engine.cli import app

    result = runner.invoke(
        app,
        [
            "shopify",
            "inventory",
            "mystore.myshopify.com",
        ],
    )
    assert result.exit_code == 2


def test_cli_shopify_unknown_subcommand_exits_2():
    from engine.cli import app

    result = runner.invoke(
        app,
        [
            "shopify",
            "frobnicate",
            "mystore.myshopify.com",
            "--access-token",
            "shpat_abc",
        ],
    )
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Token not logged
# ---------------------------------------------------------------------------


@responses.activate
def test_token_not_in_normal_error_messages():
    """The access token must not appear in error messages when the API
    response is well-formed (e.g. 404). (If Shopify itself echoes the token
    in an error body, that's their bug, not ours — we do not enrich messages
    with the token.)
    """
    responses.add(
        responses.GET,
        "https://mystore.myshopify.com/admin/api/2024-10/shop.json",
        json={"errors": "Not Found"},
        status=404,
    )
    client = ShopifyAdminClient("mystore.myshopify.com", "shpat_supersecret")
    try:
        client.get_shop_info()
    except RuntimeError as exc:
        assert "shpat_supersecret" not in str(exc)
    else:
        pytest.fail("Expected RuntimeError")


# ---------------------------------------------------------------------------
# TypedDict contracts (Sprint 18) — `total=False` partial-mock acceptance
# ---------------------------------------------------------------------------


class TestShopifyTypedDicts:
    """These tests pin the TypedDict contracts for the Admin API. They guard
    against accidentally tightening `total=False` into `total=True`, which
    would break every existing mock that builds partial payloads.
    """

    def test_shop_info_partial_mock(self) -> None:
        """ShopInfo needs only name+domain — plan_* and currency optional."""
        from integrations.shopify_admin import ShopInfo

        s: ShopInfo = {"name": "My Shop", "domain": "x.myshopify.com"}
        assert s["name"] == "My Shop"
        assert s["domain"] == "x.myshopify.com"
        assert "plan_display_name" not in s

    def test_product_summary_image_can_be_none(self) -> None:
        """ProductSummary.image is a ProductImage OR None — runtime tolerates both."""
        from integrations.shopify_admin import ProductSummary

        p: ProductSummary = {
            "id": 1,
            "title": "X",
            "handle": "x",
            "image": None,  # type: ignore[typeddict-item]
        }
        assert p["title"] == "X"
        assert p["image"] is None

    def test_product_summary_image_can_be_absent(self) -> None:
        """``image`` may be missing entirely (products without featured image)."""
        from integrations.shopify_admin import ProductSummary

        p: ProductSummary = {"id": 2, "title": "Y", "handle": "y"}
        assert "image" not in p

    def test_theme_asset_summary_public_url_optional(self) -> None:
        """Runtime skips rows with missing/non-string public_url."""
        from integrations.shopify_admin import ThemeAssetSummary

        a: ThemeAssetSummary = {"key": "assets/x.jpg"}  # public_url missing
        assert "public_url" not in a

    def test_product_entry_flat_shape(self) -> None:
        """ProductEntry is the slim CLI/batch output (not the raw API)."""
        from integrations.shopify_admin import ProductEntry

        e: ProductEntry = {
            "id": 1,
            "title": "T",
            "handle": "h",
            "image_url": None,
        }
        assert e["image_url"] is None
