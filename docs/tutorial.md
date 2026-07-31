# Tutorial — your first audit (Sprint 8, TD-4)

This is a hands-on walkthrough: from a clean machine to a delivered audit
report in under five minutes. For background on every flag, see
[`README.md`](../README.md) and [`docs/spec/cli_v0_1.md`](spec/cli_v0_1.md).

---

## 1. Install (`~30s`)

```bash
pipx install shopify-image-audit
```

The split is intentional: the core CLI doesn't pull in WeasyPrint
(~150 MB of native deps). PDF export is an opt-in extra:

```bash
pipx install 'shopify-image-audit[pdf]'
# Linux only: sudo apt-get install libpango-1.0-0 libcairo2 libgdk-pixbuf-2.0-0
```

Verify:

```bash
audit version
# shopify-image-audit 0.7.0
```

---

## 2. Audit a live URL (`~10s`)

PageSpeed Insights is the only outbound dependency:

```bash
audit measure https://kauppa.myshopify.com
# {"lcp": 4.2, "cls": 0.18, "inp": 0.32, ...}
```

Want a JSON file instead? Use `-o`:

```bash
audit measure https://kauppa.myshopify.com -o metrics.json
```

The result is cached for an hour by default. Set
`PAGESPEED_CACHE_TTL=0` to bypass, or pass `--no-cache` for a one-shot
fresh fetch.

---

## 3. Run a full Lighthouse + audit pipeline (`~45s`)

Requires `lighthouse` on `PATH` (`npm i -g lighthouse`):

```bash
audit run https://kauppa.myshopify.com --runs 3 --device mobile
# -> artifacts/audit_result.json (schema-compliant)
# -> artifacts/lhr_run1.json (raw Lighthouse)
```

The HTML report writes to `report.html` by default:

```bash
audit report artifacts/audit_result.json -o report.html
# -> report.html (open in browser)

# Or PDF:
audit report artifacts/audit_result.json --pdf -o report.pdf
```

---

## 4. Capture a baseline, then compare (`~60s`)

The before/after workflow (Sprint 2) is the headline use case for
customers who optimise their images:

```bash
# Step 1: capture the current state
audit baseline fixtures/before_after/before_lcp.json \
    --save baseline.json \
    --url https://kauppa.myshopify.com \
    --label "Pre-optimisation"

# ... customer optimises images ...

# Step 2: audit the new state
audit baseline fixtures/before_after/after_lcp.json \
    --save after.json \
    --url https://kauppa.myshopify.com \
    --label "Post-optimisation"

# Step 3: compare
audit compare baseline.json after.json -o diff.html --brand-color "#ff6b35"
# open diff.html → see the ROI
```

`diff.html` includes a brand-coloured ROI summary box, per-image deltas,
and prioritised recommendations.

---

## 5. Schedule recurring audits (`~5s`)

For customers who want daily or weekly re-audits, the **external cron
model** is the simplest path. See
[`docs/runbook/scheduled_reaudit.md`](runbook/scheduled_reaudit.md) for
the full story; the essentials:

```bash
# 1. Add a schedule
audit schedule add kauppa.myshopify.com https://kauppa.myshopify.com \
    --label "Daily 09:00"

# 2. Test it
audit schedule run-all --api-key YOUR_KEY

# 3. Add a crontab line (Linux/macOS)
crontab -e
# 0 9 * * * /usr/local/bin/audit schedule run-all --api-key YOUR_KEY >> /var/log/shopify-audit.log 2>&1
```

After a few runs, view the trend:

```bash
audit history list kauppa.myshopify.com
audit history show kauppa.myshopify.com -o trend.html
```

---

## 6. Multi-store inventory audit (`~15s`)

For agencies managing several Shopify stores, the batch path fetches
product + theme-asset image URLs across all of them in parallel:

```bash
# stores.json — one entry per store
cat > stores.json <<'EOF'
[
  {"shop_domain": "store-a.myshopify.com", "access_token": "shpat_xxx"},
  {"shop_domain": "store-b.myshopify.com", "access_token": "shpat_yyy"}
]
EOF

audit shopify batch --stores-file stores.json -o inventory.json \
    --parallel 4 --access-token-fallback
```

Outputs one combined JSON with `shop_domain` stamped on every image.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'weasyprint'`**
Install the `[pdf]` extra.

**`Backend failure: PageSpeed API rate limit exceeded`**
Set `PAGESPEED_CACHE_TTL=0` and pass `--api-key` for higher limits; or
wait a minute and retry.

**`Could not find the lighthouse binary`**
`npm i -g lighthouse` (or pass `--lhr <file>` to use a pre-existing
report).

**`--output must be a relative path`**
The CLI's path-safety check rejects absolute paths and `..` traversal.
Run from the directory where you want the file, or pass a relative
filename.

---

## Where to next?

- [`docs/spec/cli_v0_1.md`](spec/cli_v0_1.md) — every command + flag documented
- [`docs/runbook/scheduled_reaudit.md`](runbook/scheduled_reaudit.md) —
  crontab, systemd, flock examples
- [`docs/runbook/measurement_protocol.md`](runbook/measurement_protocol.md) —
  how `--runs` interacts with the audit pipeline
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — for contributing code or docs