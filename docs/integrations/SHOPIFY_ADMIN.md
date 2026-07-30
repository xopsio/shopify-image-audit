# Shopify Admin API Integration

The `audit shopify` subcommands connect to a Shopify store's **Admin REST API**
to verify access tokens and list image URLs (products + theme assets).
This eliminates the need for the customer to export a Lighthouse JSON report
by hand — the tool can fetch everything it needs directly.

## Token acquisition

To use `audit shopify`, you need an **Admin API access token** for the
target store. Tokens are scoped per app; create a private/custom app to
mint one.

### 1. Create a private app in the Shopify admin

1. In your Shopify admin, go to **Settings → Apps and sales channels**.
2. Click **Develop apps → Create an app**.
3. Give the app a name (e.g. `shopify-image-audit`) and a contact email.
4. Click **Create app**.

### 2. Configure Admin API scopes

On the new app's page, click **Configure Admin API scopes**, then enable
the **read-only** scopes the tool needs:

- `read_products` — list products and featured image URLs
- `read_themes` — list theme assets (image filenames in the active theme)
- `read_shop` — read basic shop information (name, plan, currency)

You do **not** need any write scopes — the tool is strictly read-only.

Save the scopes when prompted.

### 3. Install the app and copy the access token

1. Click **Install app** in the top-right of the app's page.
2. Confirm the installation in the modal.
3. Reveal and copy the **Admin API access token** (`shpat_…` or
   `shpca_…` prefix).

> **Treat this token like a password.** Anyone with the token can read
> product/theme data from your store.

## Usage

### Verify the token works

```bash
audit shopify auth mystore.myshopify.com --access-token shpat_xxxxxxxx
# -> ✓ Token valid
#    Name:     My Store
#    Domain:   mystore.myshopify.com
#    Plan:     Basic
#    Currency: USD
```

The token can also come from the `SHOPIFY_ACCESS_TOKEN` environment variable
(useful for CI / shell history hygiene):

```bash
export SHOPIFY_ACCESS_TOKEN=shpat_xxxxxxxx
audit shopify auth mystore.myshopify.com
```

### List all image URLs in the store

```bash
audit shopify inventory mystore.myshopify.com --access-token shpat_xxxxxxxx
# Prints one line per image:
#   [product     ] https://cdn.shopify.com/...
#   [theme_asset  ] https://cdn.shopify.com/.../assets/hero.jpg
```

To write the inventory to a JSON file (one entry per image, with `source`,
`title`/`key`/`theme`, and `url`):

```bash
audit shopify inventory mystore.myshopify.com \
    --access-token shpat_xxxxxxxx \
    -o inventory.json
```

Limit the number of products (default 50, max 250):

```bash
audit shopify inventory mystore.myshopify.com --limit 100
```

## Exit codes

| Code | Meaning |
|-----:|---------|
| 0    | Success |
| 2    | Invalid arguments (missing token, bad shop domain, etc.) |
| 10   | Backend failure (Shopify API error, rate limit, network) |

## API surface

`ShopifyAdminClient` is in `src/integrations/shopify_admin.py`:

- `__init__(shop_domain, access_token, *, timeout=30, max_retries=3, retry_delay=2)`
- `get_shop_info() -> dict` — name, domain, plan, currency
- `get_products(limit=50) -> list[dict]` — id, title, handle, image_url
- `get_theme_assets() -> list[dict]` — theme_name, key, url (images only)

All methods retry on HTTP 429 (rate limit) and 503 (transient) with linear
backoff. Network errors propagate as `requests.exceptions.RequestException`.

The Admin API rate limit is 40 requests per 2 seconds (per store). The
client respects this by sleeping 50 ms between calls.

## Security notes

- The access token is **never logged**. Error messages do not include it.
- Only read-only scopes are required — do not grant write access.
- If a token is compromised, revoke it in the Shopify admin and create
  a new app. There is no auto-rotation.
- For team use, create one app per developer; do not share tokens.
