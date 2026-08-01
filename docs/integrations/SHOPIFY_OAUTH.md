# Shopify Admin OAuth (Sprint 19, v0.15.0)

The `audit shopify login` command automates the manual custom-app
token flow. Instead of creating an app in the Shopify admin,
configuring scopes, installing it, and copy-pasting the token, the
CLI opens the user's browser to the official OAuth flow, waits for
the callback, and stores the resulting access token in a dedicated
`tokens.json` file.

## When to use this vs. manual tokens

Use `audit shopify login` if:

- You're running this on a workstation with a browser.
- You already have a custom app created in the Shopify Partner
  dashboard (just need the client_id / client_secret).
- You want the token auto-refreshable (re-run `login` whenever the
  token expires — though Admin tokens don't expire, you may want to
  rotate after staff changes).

Use the **manual flow** documented in `SHOPIFY_ADMIN.md` if:

- You're running on a headless server without a browser. The CLI will
  print the authorize URL for you to paste into a browser
  elsewhere; the embedded callback server still listens on
  `localhost`.
- You want to keep the token outside of any file this tool writes.

## Setup

### 1. Create a custom app in the Partner dashboard

1. Visit `https://<your-store>.myshopify.com/admin/settings/apps`
   (or `https://partners.shopify.com` for partner-owned apps).
2. **Develop apps → Create an app**.
3. Name it (e.g. `shopify-image-audit`) and provide a contact email.
4. **Configure Admin API scopes**: enable the read-only scopes the
   tool needs:
   - `read_products`
   - `read_themes`
   - `read_shop`
5. Save. Then **Install app** (top-right) to generate a token.
6. Reveal and copy **Client ID** and **Client secret** — you'll need
   them in step 3.

### 2. Register the redirect URL

The CLI runs a temporary HTTP listener on
`http://localhost:<port>/callback` (port is picked automatically in
`18765-18774`). The Partner dashboard requires this **exact** URL
before it will redirect users to it.

Add the URL exactly as printed by:

```bash
audit shopify login --shop mystore.myshopify.com
```

(The command prints the callback URL before opening the browser.)

> **Security note:** the callback server binds to `127.0.0.1` only —
> no external traffic is accepted. Public deployments behind a
> reverse proxy should terminate TLS at the proxy and forward to the
> same loopback port.

### 3. Run `audit shopify login`

```bash
audit shopify login mystore.myshopify.com
```

The CLI:

1. Generates a CSRF `state` nonce.
2. Starts the embedded callback server on a free loopback port.
3. Opens the user's default browser to the authorize URL.
4. Waits up to 60 seconds for the Shopify redirect.
5. Exchanges the returned `code` for an access token.
6. Writes the token to `tokens.json` with mode `0600`.

Subsequent commands (`audit shopify auth`, `audit shopify inventory`)
read the token automatically — no `--access-token` flag needed:

```bash
audit shopify auth mystore.myshopify.com
audit shopify inventory mystore.myshopify.com
```

## Configuration

The OAuth credentials can be supplied four ways (highest priority
first):

| Source | Flag / Env / Config |
|---|---|
| CLI flag | `--client-id abc` / `--client-secret shpss_...` |
| Env var | `SHOPIFY_CLIENT_ID` / `SHOPIFY_CLIENT_SECRET` |
| Config file | `[shopify] client_id = "abc"` / `client_secret = "shpss_..."` |
| Default | none — login aborts with a clear error |

Scope list defaults to `read_products,read_themes,read_shop` (matching
the custom-app flow). Override via `--scopes` or
`[shopify] scopes = "read_products,read_orders"` in `config.toml`.

## Token storage

Tokens land in `$XDG_DATA_HOME/.shopify-image-audit/tokens.json`
(default `~/.local/share/.shopify-image-audit/tokens.json`). The file
is plain JSON with **mode 0600** (POSIX). **Encryption is out of
scope for v0.15.0** — see `docs/ROADMAP.md`.

## Headless environments

The CLI prints the authorize URL before launching the browser, so
even on a headless box (no DISPLAY, ssh-only session) you can copy
the URL into a browser on your workstation and the redirect will
still reach the CLI's loopback listener.

If you cannot bind the callback port (e.g. a strict firewall blocks
loopback traffic), pass a different `--redirect-uri` via config and
set up a reverse proxy to forward to it. The CLI does not currently
expose a `--redirect-uri` flag — file an issue if you need it.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `OAuth credentials missing` | client_id / client_secret not set | Pass via flag, env, or `config.toml` |
| `OAuth timed out` (60s) | User didn't click "Install" in the browser | Re-run; consider extending the timeout |
| `state mismatch` page appears | CSRF rejection (someone else hit your URL) | Re-run; this should never happen on the legitimate flow |
| `Token exchange failed` | Network error or invalid client_secret | Verify the secret in the Partner dashboard |
| `No free TCP port in 18765-18774` | All 10 ports occupied | Free one up or use a non-loopback setup |
| `Browser failed to open` | Headless box | Copy the printed URL into a real browser |

## Security properties

- **CSRF**: every login generates a 32-byte random `state` nonce and
  the callback verifies it with `secrets.compare_digest` (constant
  time). Mismatched states are silently rejected.
- **Loopback binding**: the callback server binds to `127.0.0.1`
  only — no external interface.
- **Token storage**: `tokens.json` is created with mode `0600`.
- **No logging**: access tokens are never logged. The
  `client_secret` is only sent in the POST body to
  `access_token`; it never appears in error messages.

## Deferred (future sprints)

- Token encryption (keyring / `cryptography.fernet`).
- Multi-store batch login (`audit shopify login <stores-file>`).
- HTTPS-terminated callback for production reverse proxies.
- Public-app listing on the Shopify App Store.

See `docs/ROADMAP.md` for the full deferred list.
