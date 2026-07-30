# CLI spec

This document describes the contract for every `audit` subcommand as of
v0.6.0. The list is exhaustive — there are **11 commands** (or command
families with subcommands): `run`, `extract`, `score`, `report`, `measure`,
`baseline`, `compare`, `shopify`, `history`, `schedule`, `version`.

## Exit code conventions

| Code | Meaning |
|------|---------|
| `0`  | Success |
| `2`  | Invalid arguments (bad URL, missing file, invalid JSON, unsafe path) |
| `10` | Backend / Lighthouse / API failure |

`audit history` and `audit schedule` add a `0` (some succeeded) vs `10`
(all failed) distinction for batch operations.

---

## Commands

### `audit run <url>`

Runs Lighthouse and writes raw results.

**Flags:**
- `--device mobile|desktop` (default `mobile`)
- `--runs 3` (default 3)
- `--out-dir <path>` (default `artifacts/`)
- `--lhr <path>` (use an existing Lighthouse JSON instead of running live)

**Exit codes:** `0` success · `2` invalid args · `10` lighthouse failure.

---

### `audit extract <lighthouse.json>`

Extracts image + LCP-related features into an intermediate JSON (printed to stdout).

**Exit codes:** `0` success · `2` invalid args (missing/invalid file).

---

### `audit score <audit_input.json>`

Assigns `role`, `score` (0–100), and recommendations per image.

**Flags:**
- `--ranker heuristic|ml` (default `heuristic`)

**Exit codes:** `0` success · `2` invalid args.

---

### `audit report <audit_result.json>`

Renders an HTML or PDF report.

**Flags:**
- `-o, --output <path>` (default `report.html`; auto-switches to `report.pdf` with `--pdf`)
- `--pdf` — render PDF via WeasyPrint instead of HTML
- `--brand-logo <path>` — PNG/JPG/GIF/WebP/SVG logo embedded as data URI
- `--brand-color <hex>` — primary brand colour (`#RRGGBB` or `#RGB`)

**Exit codes:** `0` success · `2` invalid args.

---

### `audit measure <url>`

Fetches live performance metrics from the Google PageSpeed Insights API.

**Flags:**
- `--strategy mobile|desktop` (default `mobile`)
- `--api-key <key>` (optional; required for higher rate limits)
- `-o, --output <path>` (default: print JSON to stdout)
- `--no-cache` — bypass the PageSpeed response cache

**Exit codes:** `0` success · `2` invalid args · `10` API failure / rate limit.

---

### `audit baseline <lhr.json>`

Runs the audit pipeline on a Lighthouse JSON / fixture report and stores
the result as a reusable baseline (`audit_result.json`). Also records a
snapshot to `~/.local/share/.shopify-image-audit/history/<hostname>/`.

**Flags:**
- `--save <path>` (required) — where to write the baseline
- `--url <url>` (optional) — override the store URL in the baseline meta
- `--device mobile|desktop` (default `mobile`)
- `--history-dir <path>` (optional) — override the audit-history directory
- `--label <text>` (optional) — human-readable label for the history entry

**Exit codes:** `0` success · `2` invalid args · `10` pipeline failure.

---

### `audit compare <baseline.json> <current>`

Compares a baseline audit against a current audit and reports before/after deltas.

Each input may be:
- a saved `audit_result.json` (from `audit baseline`)
- a raw Lighthouse/fixture report (run through the audit pipeline)
- **a live URL** (`http://` / `https://`) — fetched via PageSpeed Insights API

**Flags:**
- `-o, --output <path>` — write an HTML before/after report (default: stdout JSON)
- `--pdf` — when `--output` is set, render a PDF instead of HTML
- `--json <path>` — also write the comparison JSON
- `--strategy mobile|desktop` — PageSpeed strategy when `<current>` is a URL
- `--api-key <key>` — optional Google Cloud API key
- `--brand-logo <path>` — pass through to the HTML/PDF report
- `--brand-color <hex>` — pass through to the HTML/PDF report
- `--no-cache` — bypass the PageSpeed response cache

**Output:** `ComparisonResult` (vitals deltas + image aggregate deltas + ROI
estimate + per-image deltas). Units mirror `Vitals`: ms for LCP/INP/TTFB,
unitless for CLS. `per_image` field is a list of `ImageDelta` objects.

**Exit codes:** `0` success · `2` invalid args · `10` backend failure.

---

### `audit shopify <subcommand> [args]`

Interact with a Shopify store via the Admin API.

**Subcommands:** `auth`, `inventory`, `batch`.

**Common flags:**
- `--access-token <token>` (can also be set via `$SHOPIFY_ACCESS_TOKEN`)

#### `audit shopify auth <shop_domain>`
Verifies the access token by fetching shop info. Prints shop name, domain,
plan, currency.

#### `audit shopify inventory <shop_domain>`
Lists image URLs: products + theme assets.

**Flags:**
- `-o, --output <path>` — write JSON to file (default: print to stdout)
- `--limit <N>` (1–250, default 50)

#### `audit shopify batch --stores-file <path>`
Multi-store inventory audit (Sprint 6, TD-3). Reads a JSON array of
`{shop_domain, access_token}` entries, fetches inventory for each, merges
results.

**Flags:**
- `--stores-file <path>` (required) — JSON file with array of store configs
- `-o, --output <path>` — write combined JSON
- `--parallel <N>` (default 1) — concurrent stores; 0 = all in parallel
- `--stop-on-error` — abort on first failure (default: continue)

**Exit codes:** `0` success (some/all) · `2` invalid args (bad JSON) ·
`10` all stores failed.

---

### `audit history <subcommand> <hostname>`

Inspect audit history for a store.

**Subcommands:** `list`, `show`, `diff`.

#### `audit history list <hostname>`
Rich table of past audits for the hostname.

#### `audit history show <hostname>`
Generates a trend HTML report.

**Flags:**
- `-o, --output <path>` (default: `<hostname>-history.html`)
- `--history-dir <path>`

#### `audit history diff <hostname> --from <id> --to <id>`
Generates a before/after comparison HTML from two historical snapshots.

**Flags:**
- `--from <id>` (required) — source entry id (the older "before" snapshot)
- `--to <id>` (required) — target entry id (the newer "after" snapshot)
- `-o, --output <path>` (default: `<hostname>-diff-<id1>-<id2>.html`)
- `--history-dir <path>`

Entry ids are 12-char SHA-256 prefixes shown by `audit history list`.

**Exit codes:** `0` success · `2` invalid args (missing ids, unknown ids).

---

### `audit schedule <subcommand>`

Manage scheduled re-audits (Sprint 7, TD-1). Scheduling itself is
delegated to cron / systemd timer — see
[`docs/runbook/scheduled_reaudit.md`](../runbook/scheduled_reaudit.md).

**Subcommands:** `list`, `add`, `remove`, `run-all`.

#### `audit schedule list`
Rich table of configured schedules (from `schedules.json`).

#### `audit schedule add <shop_domain> <url>`
Adds a schedule entry.

**Flags:**
- `--device mobile|desktop` (default `mobile`)
- `--label <text>` (optional)
- `--schedule-dir <path>`

#### `audit schedule remove <shop_domain>`
Drops a schedule entry.

#### `audit schedule run-all`
Executes every configured schedule (fetches via PageSpeed, records to
history). Per-store failures are warnings by default.

**Flags:**
- `--history-dir <path>`
- `--api-key <key>`
- `--schedule-dir <path>`

**Exit codes:** `0` success (some/all) · `10` all schedules failed.

---

### `audit version`

Prints the tool version, read from `pyproject.toml` at runtime.

**Exit code:** `0` success.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `WARNING` | Logging level (`DEBUG` for verbose output) |
| `XDG_DATA_HOME` | `~/.local/share` | Base dir for schedules.json + history/ + cache/ |
| `PAGESPEED_CACHE_TTL` | `3600` | PageSpeed response cache TTL in seconds (`0` disables) |
| `SHOPIFY_ACCESS_TOKEN` | (none) | Admin API token for `audit shopify` commands |

---

## Required final output

`audit_result.json` MUST validate against `schemas/audit_result.schema.json`.

Comparison outputs (`ComparisonResult`) are a separate data contract, not part
of `audit_result.schema.json`.