# Roadmap — Shopify Image Audit

**Last updated:** 2026-07-31 (Sprint 9 complete, v0.7.1 released)
**Owner:** ZCode (single-agent, governance v1.3)

---

## Phases

The project is structured in three phases. The first three are operational;
the fourth targets scalability and recurring revenue.

### Phase 1 — Manual audit tool (✅ DONE, Sprint 1)

> Goal: a working CLI that produces a customer-ready audit report.

- ✅ CLI commands: `run`, `extract`, `score`, `report`, `measure`
- ✅ Pydantic v2 models + JSON schema contract
- ✅ Heuristic ranker (`bpp` + LCP penalty)
- ✅ HTML report
- ✅ PageSpeed Insights integration (live LCP/CLS/INP)
- ✅ Customer report template + onboarding guide
- ✅ Example report (`docs/examples/demo_audit_report.html`)
- ✅ Sprint 1 retrospective: 103 tests, governance v1.1

### Phase 2 — Before/after measurement (✅ DONE, Sprint 2)

> Goal: prove ROI to customers with a baseline → optimise → re-measure workflow.

- ✅ Baseline persistence (`save_baseline`/`load_baseline`)
- ✅ Comparison engine (`core/baseline_manager.py`)
- ✅ `audit baseline` + `audit compare` CLI
- ✅ HTML report with before/after section
- ✅ Vitals + image deltas + ROI estimate
- ✅ `comparison.json` schema (separate data contract)
- ✅ Live URL support in `compare` via PageSpeed API
- ✅ ML-style ranker (`ranker_ml.py`, opt-in `ranker=ml`)
- ✅ CI workflow (GitHub Actions, Python 3.11+3.12)
- ✅ Branch protection on `main`
- ✅ Ruff clean (168 → 0 violations)
- ✅ Customer onboarding guide + demo report

### Phase 3 — Revenue expansion (✅ DONE, Sprint 3)

> Goal: turn the manual audit-on-demand into a product that scales — both
> in deliverable quality and in workflow integration.

- ✅ **TD-1**: PDF export (`report --pdf`, `compare --pdf`, WeasyPrint)
- ✅ **TD-2**: Per-image before/after deltas (2-phase matching: hash + src fallback)
- ✅ **TD-3**: Shopify Admin API client (`audit shopify auth`/`inventory`)
- ✅ **TD-4**: v0.2.0 release prep (trusted publishing, release workflow)
- ✅ Release workflow hardening (structural build/publish split)

### Phase 4 — Scalability & recurring revenue (✅ DONE, Sprint 4)

> Goal: make the tool useful to *repeat* customers, not just first-time audits.

- ✅ **TD-1**: Documentation & tech-debt cleanup
- ✅ **TD-2**: Branded report templates (--brand-logo, --brand-color)
- ✅ **TD-3**: ROI-ranked recommendations (ComparisonRecommendation model)
- ✅ **TD-4**: Audit history + trend view (HistoryStore, `audit history list/show`)
- ✅ **v0.3.0 release** (489 tests, PyPI trusted publishing)

### Phase 5 — Reliability & DX (✅ DONE, Sprint 5)

> Goal: lock down the existing surface area and ship the deferred `history diff` command.

- ✅ **TD-1**: Snapshot testing infrastructure (syrupy, 22 golden files)
- ✅ **TD-2**: CLI coverage close-out (all 10 commands have happy-path tests)
- ✅ **TD-3**: Wire error decorators + consistency pass (RuntimeError → exit 10 across the board)
- ✅ **TD-4**: `audit history diff` with stable entry-ids; CHANGELOG.md; `--cov-fail-under=85` CI gate
- ✅ **v0.4.0 release** (546 tests, 91.24% coverage, ruff clean)

### Phase 6 — Coverage, Isolation, Batch & Observability (✅ DONE, Sprint 6)

> Goal: lock down remaining coverage gaps, harden test isolation, ship multi-store
> batch, and add operator-friendly observability.

- ✅ **TD-1**: Coverage close-out — `_table.py` 68% → 100%, total 91.24% → 93%
- ✅ **TD-2**: Test isolation hardening — zero `Path("foo")` writes or `os.chdir` in tests
- ✅ **TD-3**: Multi-store batch — `audit shopify batch --stores-file <path>` (sequential + parallel)
- ✅ **TD-4**: Observability + docs + v0.5.0 release
  - `engine._logging` centralised logger (6 hooks)
  - `CONTRIBUTING.md` with WeasyPrint install + snapshot workflow
  - Coverage gate `--cov-fail-under=85` → `--cov-fail-under=90`
- ✅ **v0.5.0 release** (606 tests, 93% coverage, ruff clean)

### Phase 7 — Scheduled Re-audit, Dependency Hygiene & Report Polish (✅ DONE, Sprint 7)

> Goal: close the oldest open thread (scheduled re-audit, deferred since Sprint 4)
> via external cron; add Dependabot, SLSA provenance, and PageSpeed response
> cache; fix report footer version drift; refresh CLI spec docs.

- ✅ **TD-1**: Scheduled re-audit — `audit schedule list/add/remove/run-all` + crontab runbook
- ✅ **TD-2**: Dependency hygiene — Dependabot (pip + github-actions), SLSA provenance, dep upper caps
- ✅ **TD-3**: PageSpeed response cache — `PAGESPEED_CACHE_TTL` env var, report footer version fix
- ✅ **TD-4**: Docs polish + v0.6.0 release
  - CLI spec rewritten to cover all 11 commands
  - README `pipx install` Deployment section + Lighthouse CLI prerequisite
  - Measurement protocol doc accurate
- ✅ **v0.6.0 release** (642 tests, ruff clean)

---

## Phase 4 themes (high-level)

### Theme A — Deliverable polish
- ✅ PDF export (Sprint 3)
- ✅ Per-image comparison (Sprint 3)
- ✅ Branded report template — customer logo + colours (Sprint 4 TD-2)

### Theme B — Workflow integration
- ✅ Shopify Admin API client (Sprint 3)
- ✅ Audit history + trend view (Sprint 4 TD-4)
- 🔜 Scheduled re-audit (Sprint 5+, requires infra decisions)

### Theme B — Workflow integration (post-Sprint 6)
- ✅ Scheduled re-audit (Sprint 7, external-cron model — `audit schedule add/run-all`)
- 🔜 In-process scheduler daemon — out of scope; external cron is sufficient

### Theme C — Smarter recommendations
- ⚠️ Real ML ranker — partially addressed by weighted ensemble (deliberate, see decision log)
- ✅ Recommendation prioritisation by ROI (Sprint 4 TD-3)
- ❌ Image-optimisation automation hooks (out of scope — sister tool)

### Theme D — Reliability
- ✅ CLI distribution (PyPI v0.2.0 → v0.7.0, trusted publishing)
- ✅ Release automation (tag-driven, hardened, SLSA provenance in v0.6.0)
- ✅ Snapshot tests for HTML report (Sprint 5 TD-1, syrupy, 22 golden files)
- 🔜 SBOM generation — deferred (Sprint 10+; low priority)
- 🔜 User-side TOML config — deferred (Sprint 10+)
- 🔜 Mypy rollout — deferred (Sprint 10+ with TypedDict sweep)

### Theme E — UX & DX (Sprint 8+)
- ✅ "Did you mean: X?" suggestions on every typo site (Sprint 8 TD-1)
- ✅ `tests/conftest.py` consolidation (Sprint 8 TD-2)
- ✅ `run_parallel` shared helper (Sprint 8 TD-3)
- ✅ `[pdf]` optional extra — saves ~150 MB on non-PDF installs (Sprint 8 TD-4)
- ✅ `docs/tutorial.md` walkthrough (Sprint 8 TD-4)

---

## Out of scope (forever / for now)

- **C# extension layer** — deferred indefinitely (Python tooling covers all needs)
- **GPU acceleration** — not relevant (I/O-bound on PageSpeed)
- **Automated image transformation** — different product (Shopify has built-in)
- **Multi-store batch** — ✅ DONE in v0.5.0 (Sprint 6 TD-3): `audit shopify batch --stores-file`
- **OAuth flow for Shopify Admin** — token-only in v1; custom-app tokens work
- **Real ML model training** — hand-coded weighted ensemble is deliberate
- **Async HTTP layer** — deferred (Sprint 10+); current `ThreadPoolExecutor` + `requests` covers the use case, and the on-disk PageSpeed cache mitigates the only real pain point (rate limits)
- **Branded CSS themes per customer** — out of scope; `--brand-color` + `--brand-logo` cover the v1 customer need
- **Standalone `docs/architecture.md`** — out of scope; the ASCII tree in `README.md` is enough for v1

---

## Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-01 | Adopt 3×3 multi-agent model | Original governance; obsolete after exits |
| 2026-03-08 | Formalise `src/audit/` ownership | Single-writer rule needed |
| 2026-07-29 | ZCode absorbs Claude domains | Claude exited; engine needed an owner |
| 2026-07-30 | ZCode absorbs all worker domains | Single-agent model (v1.3) |
| 2026-07-30 | ML ranker is a weighted ensemble, not sklearn | Deterministic + testable beats opaque model |
| 2026-07-30 | Branch protection enabled on `main` | First time CI actually protects the codebase |
| 2026-07-30 | Structural build/publish split in release workflow | Shell-level dry_run was fragile; job-level if is stronger |
| 2026-07-30 | SLSA build-provenance attestation on every release | `actions/attest-build-provenance@v2` non-blocking; PyPI consumers can verify build origin |
| 2026-07-30 | External-cron model for scheduled re-audit | Avoids in-process daemon; standard cron + flock covers the use case; defers infra decisions (systemd / K8s) to a future sprint |
| 2026-07-30 | On-disk PageSpeed response cache | Mitigates the only real pain point (free-tier rate limits); TTL-configurable via `PAGESPEED_CACHE_TTL`; `--no-cache` bypasses |
| 2026-07-30 | `run_parallel` shared concurrency primitive | `batch.py` and `scheduler.py` share the same shape; one helper reduces drift |
| 2026-07-31 | WeasyPrint moved to optional `[pdf]` extra | Saves ~150 MB on non-PDF installs; friendly `ImportError` with install hint when missing |

---

## Version history

| Phase | Date | Status | Tests | PRs (cumulative) |
|-------|------|--------|-------|------------------|
| 1 | 2026-03 | ✅ Complete | 103 | 16 |
| 2 | 2026-07 | ✅ Complete | 276 | 28 |
| 3 | 2026-07 | ✅ Complete | 390 | 40 |
| 4 | 2026-07 | ✅ Complete | 489 | 44 |
| 5 | 2026-07 | ✅ Complete | 546 | 48 |
| 6 | 2026-07 | ✅ Complete | 606 | 52 |
| 7 | 2026-07 | ✅ Complete | 642 | 56 |
| 8 | 2026-07 | ✅ Complete | 665 | 60 |
| 9 | 2026-07 | ✅ Complete | 672 | 64 |

See [`docs/`](.) for the full documentation tree.
