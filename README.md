# Shopify Image Audit

[![CI](https://github.com/xopsio/shopify-image-audit/actions/workflows/ci.yml/badge.svg)](https://github.com/xopsio/shopify-image-audit/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![ruff](https://img.shields.io/badge/lint-ruff-green)](https://docs.astral.sh/ruff/)
[![tests](https://img.shields.io/badge/tests-695_passing-brightgreen)](#testing)

A Lighthouse-based image audit tool for Shopify stores. Produces per-image
scores, role assignments, optimisation recommendations, and a **before/after
comparison** workflow that proves image-optimisation ROI to paying customers.

Designed for the 99–199 € audit-on-demand business model: run the audit,
deliver a customer-ready HTML report, optionally compare live metrics after
the customer implements the recommendations.

---

## Quickstart

### End-user install (PyPI)

```bash
# Recommended: pipx creates an isolated env
pipx install shopify-image-audit

# Alternative: pip into a venv
python -m venv .venv && source .venv/bin/activate
pip install shopify-image-audit
```

The PDF renderer (`audit report --pdf`) requires native libraries
(`libpango`, `libcairo`, `libgdk-pixbuf`). On Linux:

```bash
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0
```

The `lighthouse` Node CLI is required for `audit run <url>`. Install with
`npm i -g lighthouse` (or pass `--lhr <file>` to use a pre-existing report).

### Developer install (from source)

```bash
git clone https://github.com/xopsio/shopify-image-audit.git
cd shopify-image-audit
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Verify the install
audit version
pytest -q                                              # 695 tests
```

---

## CLI commands

The tool ships with a single Typer app. Run `audit --help` for the full list;
below are the high-value entry points.

### `audit run <url>` — full Lighthouse + audit pipeline
```bash
audit run https://kauppa.myshopify.com --device mobile --runs 3 \
    --out-dir artifacts
# -> artifacts/lhr_run1.json, audit_result.json (schema-compliant)
```

### `audit baseline <lhr.json> --save baseline.json` — capture baseline
```bash
audit baseline fixtures/before_after/before_lcp.json \
    --save baseline.json \
    --url https://demo.myshopify.com
# -> Baseline saved to baseline.json
```

### `audit compare <baseline> <current>` — before/after (file or URL)
```bash
# File vs file (offline)
audit compare baseline.json fixtures/before_after/after_lcp.json \
    -o comparison.html --json comparison.json

# File vs live URL (fetches via PageSpeed Insights API)
audit compare baseline.json https://demo.myshopify.com \
    --strategy mobile --api-key YOUR_KEY \
    -o comparison.html

# HTML report includes a per-image delta table (bytes, score, status per image).
# PDF export via --pdf flag.
```
Exit codes: `0` success, `2` invalid args, `10` backend failure.

### `audit report <audit_result.json>` — HTML or PDF report
```bash
audit report baseline.json -o report.html          # HTML
audit report baseline.json -o report.pdf --pdf     # PDF (WeasyPrint)
```

### `audit measure <url>` — live PageSpeed metrics only
```bash
audit measure https://demo.myshopify.com --strategy mobile
# -> JSON metrics to stdout (or --output metrics.json)
```

### `audit shopify <auth|inventory> <store>` — Shopify Admin API
```bash
# Verify a token
audit shopify auth mystore.myshopify.com --access-token shpat_xxx
# -> Token valid, prints shop info

# List all image URLs (products + theme assets)
audit shopify inventory mystore.myshopify.com --access-token shpat_xxx -o inventory.json
```
Read-only scopes required (`read_products`, `read_themes`, `read_shop`).
See `docs/integrations/SHOPIFY_ADMIN.md` for token-acquisition steps.

### `audit score <audit_input.json> --ranker {heuristic|ml}`
```bash
audit score extracted.json                    # default: heuristic
audit score extracted.json --ranker ml        # weighted feature ensemble
```

Full reference: [`docs/spec/cli_v0_1.md`](docs/spec/cli_v0_1.md).

---

## Scoring algorithms

The pipeline assigns each image a `role`, a `score` (0–100), and a
`recommendation`. Two rankers ship, switchable via `--ranker ml`:

| Ranker | Formula | Use case |
|--------|---------|----------|
| `heuristic` (default) | bytes per displayed pixel (bpp) + LCP penalty | fast, predictable baseline |
| `ml` | weighted ensemble: f_size, f_density, f_format, f_dim_match + LCP strictness | richer signal, more honest scoring |

Both produce the same output contract (role + score + recommendation). The ML
ranker is a hand-coded feature ensemble, not a statistical model — see
[`src/audit/ranker_ml.py`](src/audit/ranker_ml.py) for the design rationale
(no model deps, deterministic, fully explainable via `ml_features()`).

---

## Configuration

Repeated options can be set once in
`~/.config/shopify-image-audit/config.toml` (or
`$XDG_CONFIG_HOME/shopify-image-audit/config.toml`):

```toml
[defaults]
device = "mobile"    # run / baseline / schedule add
strategy = "mobile"  # measure / compare
parallel = 4         # shopify batch / schedule run-all (0 = unlimited)

[pagespeed]
api_key = "AIza..."  # or --api-key / $PAGESPEED_API_KEY

[report]
brand_color = "#ff6b35"   # report / compare branding
```

Precedence: **CLI flag > env var > config > default**. A broken config
warns and falls back to defaults — it never blocks a run. Full reference
(13 keys / 5 sections) in [CONTRIBUTING §5b](CONTRIBUTING.md).

---

## Architecture

```
src/
├── audit/                    # scoring + reporting
│   ├── models.py             # Pydantic v2 schemas (AuditResult, ComparisonResult, ImageDelta)
│   ├── parser.py             # Lighthouse / fixture JSON parser
│   ├── ranker_heuristic.py   # default ranker (bpp-based)
│   ├── ranker_ml.py          # opt-in ML-style ranker (weighted ensemble)
│   └── report.py             # HTML/PDF report renderer (split into _render_* funcs)
├── core/                     # core algorithms
│   ├── image_extractor.py    # LHR image audit extraction
│   ├── image_signals.py      # shared displayed_area, assign_role, _safe_int
│   └── baseline_manager.py   # save/load baselines + compare() + per-image matching
├── engine/                   # orchestration + CLI
│   ├── cli.py                # Typer app (run, measure, baseline, compare, shopify, ...)
│   ├── cli_helpers/          # extracted CLI helpers (validators, dispatchers, table, errors)
│   └── audit_orchestrator.py # run_audit() pipeline
└── integrations/             # external APIs
    ├── pagespeed_api.py      # PageSpeed Insights (measure + fetch_lighthouse_json)
    └── shopify_admin.py      # Shopify Admin API (auth, products, theme_assets)

src/audit/schemas/audit_result.schema.json  # JSON Schema contract (validated by tests)
tests/                              # 695 tests, single-writer (ZCode)
docs/examples/                       # live demo report + comparison JSON
docs/integrations/                   # Shopify Admin API token guide
```

The codebase is governed by **a single ZCode agent** (see
[`docs/governance.md`](docs/governance.md) v1.3).

---

## Testing

```bash
pytest -q                                # 695 tests, single-writer discipline
pytest --cov=src --cov-report=term       # ~91% coverage
ruff check src/ tests/                   # 0 violations
```

The CI workflow runs `pytest -q` + `ruff check` on Python 3.11 and 3.12 for
every PR. Branch protection on `main` requires both checks to pass before
merge. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## Customer deliverables (Phase 1)

- **Customer report template** — [`docs/CUSTOMER_REPORT_TEMPLATE.md`](docs/CUSTOMER_REPORT_TEMPLATE.md)
- **Onboarding workflow** — [`docs/CUSTOMER_ONBOARDING.md`](docs/CUSTOMER_ONBOARDING.md)
- **Example audit report** (Nordic Lifestyle demo store, LCP 4200ms → 1800ms) — [`docs/examples/demo_audit_report.html`](docs/examples/demo_audit_report.html)
- **Example comparison data** — [`docs/examples/demo_comparison.json`](docs/examples/demo_comparison.json)

---

## Roadmap

- ✅ Sprint 1 — v0.1.0 baseline (parser, ranker, orchestrator, CLI, HTML report, 103 tests)
- ✅ Sprint 2 — before/after workflow, customer docs, ML ranker, live URL compare, CI, governance cleanup (276 tests)
- ✅ Sprint 3 — PDF export, per-image deltas, Shopify Admin API, v0.2.0 release prep (390 tests)
- ✅ Sprint 4 — Branded reports, ROI-ranked recs, audit history, v0.3.0 (489 tests)
  - Branded report templates (--brand-logo, --brand-color)
  - ROI-ranked recommendations (ComparisonRecommendation model)
  - Audit history + trend view (HistoryStore, `audit history list/show`)
- ✅ Sprint 5 — Snapshot tests, CLI coverage, error decorator wiring, history diff, v0.4.0 (546 tests)
  - Snapshot testing infrastructure (syrupy) for HTML renderers
  - CLI coverage for all 10 commands
  - Error decorator wiring + consistency pass (RuntimeError → exit 10)
  - `audit history diff` with stable entry-ids
  - `CHANGELOG.md` and `--cov-fail-under=85` CI gate
- ✅ Sprint 6 — Coverage close-out, test isolation, multi-store batch, observability, v0.5.0 (606 tests)
  - `tests/test_table_snapshots.py` (Rich Console captures)
  - Zero CWD-relative writes in tests
  - `audit shopify batch --stores-file` for multi-store inventory
  - `engine._logging` with 6 structured log hooks
  - `CONTRIBUTING.md`, `--cov-fail-under=90`
- ✅ Sprint 7 — Scheduled re-audit, dependency hygiene, PageSpeed cache, v0.6.0 (642 tests)
  - `audit schedule list/add/remove/run-all` + crontab runbook
  - Dependabot + SLSA build-provenance attestation
  - PageSpeed response cache (`PAGESPEED_CACHE_TTL`)
  - Report footer version drift fixed
- ✅ Sprint 8 — UX polish, test architecture, shared run_parallel, v0.7.0 (665 tests)
  - "Did you mean: X?" suggestions on every typo site
  - `tests/conftest.py` + `tests/__init__.py` (single source of truth for `REPO_ROOT` + fixtures)
  - Shared `run_parallel` helper (batch + scheduler share it)
  - `audit schedule run-all --parallel` (deferred from Sprint 7)
  - `[pdf]` extra — WeasyPrint no longer required by default
  - `docs/tutorial.md` walkthrough
- ✅ Sprint 9 — Doc hygiene, wheel packaging, security polish, v0.7.1 (672 tests)
  - JSON schema ships inside the wheel (`importlib.resources`-readable)
  - `PAGESPEED_API_KEY` env var + API-key redaction in error messages
  - `schedules.json` written with `0600` permissions
  - Issue templates (bug report + feature request)
  - Doc hygiene: canonical env-var reference, drift-free test counts
- ✅ Sprint 10 — Type safety + SBOM, v0.8.0 (672 tests)
  - Mypy CI-gate, zero `type: ignore` comments
  - `ImageDict` TypedDict contract across the pipeline
  - CycloneDX SBOM in release artifacts (complements SLSA provenance)
- ✅ Sprint 11 — User-side TOML config, v0.9.0 (695 tests)
  - `~/.config/shopify-image-audit/config.toml` (13 keys / 5 sections)
  - Precedence: CLI flag > env var > config > default
  - Broken config warns + falls back — never blocks a run

---

## Further reading

- [`docs/spec/cli_v0_1.md`](docs/spec/cli_v0_1.md) — full CLI specification
- [`docs/governance.md`](docs/governance.md) — ownership + workflow
- [`docs/runbook/measurement_protocol.md`](docs/runbook/measurement_protocol.md) — how LCP/CLS/INP are measured deterministically
- [`docs/SPRINT_1_COMPLETE.md`](docs/SPRINT_1_COMPLETE.md) — what shipped in Sprint 1
- [`docs/SPRINT_3_PLAN.md`](docs/SPRINT_3_PLAN.md) — Sprint 3 breakdown (all done)
- [`docs/SPRINT_4_PLAN.md`](docs/SPRINT_4_PLAN.md) — Sprint 4 breakdown (all done)
- [`docs/SPRINT_5_PLAN.md`](docs/SPRINT_5_PLAN.md) — Sprint 5 breakdown (all done)
- [`QA_CHECKLIST.md`](QA_CHECKLIST.md) — quality gates