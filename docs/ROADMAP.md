# Roadmap — Shopify Image Audit

**Last updated:** 2026-07-30 (Sprint 5 complete, v0.4.0 released)
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

### Theme C — Smarter recommendations
- ⚠️ Real ML ranker — partially addressed by weighted ensemble (deliberate, see decision log)
- ✅ Recommendation prioritisation by ROI (Sprint 4 TD-3)
- ❌ Image-optimisation automation hooks (out of scope — sister tool)

### Theme D — Reliability
- ✅ CLI distribution (PyPI v0.2.0 / v0.3.0 / v0.4.0, trusted publishing)
- ✅ Release automation (tag-driven, hardened)
- ✅ Snapshot tests for HTML report (Sprint 5 TD-1, syrupy, 22 golden files)

---

## Out of scope (forever / for now)

- **C# extension layer** — deferred indefinitely (Python tooling covers all needs)
- **GPU acceleration** — not relevant (I/O-bound on PageSpeed)
- **Automated image transformation** — different product (Shopify has built-in)
- **Multi-store batch processing** — only relevant after per-store workflow proves
- **OAuth flow for Shopify Admin** — token-only in v1
- **Real ML model training** — hand-coded ensemble is deliberate

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

---

## Version history

| Phase | Date | Status | Tests | PRs (cumulative) |
|-------|------|--------|-------|------------------|
| 1 | 2026-03 | ✅ Complete | 103 | 16 |
| 2 | 2026-07 | ✅ Complete | 276 | 28 |
| 3 | 2026-07 | ✅ Complete | 390 | 40 |
| 4 | 2026-07 | ✅ Complete | 489 | 44 |
| 5 | 2026-07 | ✅ Complete | 546 | 48 |

See [`docs/`](.) for the full documentation tree.
