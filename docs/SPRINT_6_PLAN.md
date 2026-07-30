# Sprint 6 Plan — Coverage, Isolation, Batch & Observability

**Duration:** ~2 weeks
**Status:** ✅ COMPLETE (v0.5.0 released 2026-07-30)
**Phase:** Phase 6 (complete; see [`ROADMAP.md`](ROADMAP.md))

---

## 1. Sprint 6 Goal

Lock down remaining test-coverage gaps, harden test isolation, ship the
deferred `audit shopify batch` subcommand for multi-store inventories, add
lightweight observability via `engine._logging`, and document the
contributor workflow in `CONTRIBUTING.md`.

### Success Criteria
- `_table.py` coverage 68% → ~95% (snapshot tests for all 4 renderers)
- Total coverage 91% → ≥95% (CI threshold raised from 85% → 90%)
- Zero CWD-relative test paths
- `audit shopify inventory --stores-file <path.json>` works end-to-end
- Six log hooks emit structured INFO/DEBUG/WARN
- `CONTRIBUTING.md` consolidates WeasyPrint install + snapshot workflow
- `v0.5.0` released to PyPI

---

## 2. Deliverables

### DEL-1: Coverage close-out (TD-1) ✅
- `tests/test_table_snapshots.py` (NEW, 16 tests): Rich Console captures
- `tests/test_pagespeed_api.py` (+8): 429 retry, Timeout, error message, wrapper
- `tests/test_history.py` (+3): XDG_DATA_HOME, corrupt file
- `tests/test_report.py` (+11): `_render_image_row` direct, needs-improvement vital

### DEL-2: Test isolation hardening (TD-2) ✅
- All `Path("foo")` writes replaced with `tmp_path / "foo"`
- All manual `os.chdir` blocks replaced with `monkeypatch.chdir(tmp_path)`

### DEL-3: Multi-store batch (TD-3) ✅
- `src/engine/batch.py` (NEW, ~170 lines): StoreConfig, parse_stores_file, run_batch
- `src/engine/cli.py`: new `audit shopify batch --stores-file --parallel --stop-on-error`

### DEL-4: Observability + docs + v0.5.0 (TD-4) ✅
- `src/engine/_logging.py` (NEW, ~70 lines): centralised logger
- 6 log hooks: audit_orchestrator, history._prune, pagespeed_api, _run_lighthouse, brand validators, sanitise_image
- `CONTRIBUTING.md` (NEW, ~150 lines): WeasyPrint install, snapshot workflow, release process
- CI threshold: `--cov-fail-under=85` → `--cov-fail-under=90`

---

## 3. Acceptance Criteria

### Quality Gates:
- [x] Total coverage 93% (above 90% threshold)
- [x] 606 tests pass (up from 546)
- [x] Ruff clean
- [x] CI green Python 3.11 + 3.12
- [x] v0.5.0 released to PyPI

### Business Success:
- [x] Coverage close-out enables confident refactoring
- [x] Multi-store batch unlocks multi-tenant usage
- [x] Observability hooks let operators debug production issues

---

## 4. Out of Scope (Sprint 6)

- ❌ Scheduled re-audit (cron/Cloud scheduler) — deferred
- ❌ mypy/pyright rollout — deferred
- ❌ Branded CSS themes per customer — out of scope
- ❌ OAuth flow for Shopify Admin — token-only in v1
- ❌ Real ML model training — out of scope
- ❌ SBOM / SLSA provenance attestation — deferred
- ❌ Dependabot / Renovate — deferred

---

## 5. Stats Summary

| Metric | v0.4.0 | v0.5.0 | Δ |
|--------|--------|--------|---|
| Tests | 546 | 606 | +60 |
| Coverage | 91.24% | 93% | +1.76 |
| CLI commands | 10 | 11 | +1 (batch) |
| Snapshot files | 22 | 22 | 0 |
| Coverage gate | 85% | 90% | +5pp |

---

See [`CHANGELOG.md`](../CHANGELOG.md) for the full release log.