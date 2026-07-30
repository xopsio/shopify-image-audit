# Roadmap — Shopify Image Audit

**Last updated:** 2026-07-30 (Sprint 2 complete)
**Owner:** ZCode (single-agent, governance v1.3)

---

## Phases

The project is structured in three phases. The first two are operational;
the third is the first revenue-grade feature expansion.

### Phase 1 — Manual audit tool (✅ DONE)

> Goal: a working CLI that produces a customer-ready audit report.

- ✅ CLI commands: `run`, `extract`, `score`, `report`, `measure`
- ✅ Pydantic v2 models + JSON schema contract
- ✅ Heuristic ranker (`bpp` + LCP penalty)
- ✅ HTML report
- ✅ PageSpeed Insights integration (live LCP/CLS/INP)
- ✅ Customer report template + onboarding guide
- ✅ Example report (`docs/examples/demo_audit_report.html`)
- ✅ Sprint 1 retrospective: 103 tests, governance v1.1

### Phase 2 — Before/after measurement (✅ DONE)

> Goal: prove ROI to customers with a baseline → optimise → re-measure workflow.

- ✅ Baseline persistence (`save_baseline`/`load_baseline`)
- ✅ Comparison engine (`core/baseline_manager.py`)
- ✅ `audit baseline` + `audit compare` CLI
- ✅ HTML report with before/after section (`generate_html_report(comparison=...)`)
- ✅ Vitals + image deltas + ROI estimate (heuristic: ~1%/100ms LCP)
- ✅ `comparison.json` schema (separate from `audit_result.schema.json`)
- ✅ Live URL support in `compare` via PageSpeed API
- ✅ ML-style ranker (`ranker_ml.py`, opt-in `ranker=ml`)
- ✅ CI workflow (GitHub Actions, Python 3.11+3.12)
- ✅ Branch protection on `main` (CI required)
- ✅ Ruff clean (168 → 0 violations)
- ✅ Customer onboarding guide + demo report

### Phase 3 — Revenue expansion (🔜 NEXT)

> Goal: turn the manual audit-on-demand into a product that scales — both
> in deliverable quality (PDF, per-image comparison) and in workflow
> integration (Shopify Admin API, automated re-runs).

Detailed ticket breakdown: [`SPRINT_3_PLAN.md`](SPRINT_3_PLAN.md).

**Theme**: make the tool useful to repeat customers, not just first-time audits.

---

## Phase 3 themes (high-level)

### Theme A — Deliverable polish
- **PDF export** of the HTML report (WeasyPrint or playwright). Required by
  most enterprise customers who can't share .html files.
- **Per-image before/after comparison** — currently cohort-level only. Each
  image should show its own size/format delta.
- **Branded report template** — customer's logo + brand colours.

### Theme B — Workflow integration
- **Shopify Admin API client** — fetch store info, products, theme settings
  directly from a Shopify store (replaces the need for the customer to share
  a Lighthouse JSON).
- **Scheduled re-audit** — cron/Cloud scheduler that re-runs compare on a
  weekly basis and emails the customer the delta.
- **Audit history** — store past audits per-store, surface trends.

### Theme C — Smarter recommendations
- **Real ML ranker** — replace the hand-coded feature ensemble with a model
  trained on a labeled dataset of past audits.
- **Image-optimisation automation hooks** — optional: produce a CLI command
  that uses `cwebp`/`avifenc` to actually compress images (out-of-scope
  for the audit tool itself, but a sister tool).
- **Recommendation prioritisation by ROI** — order by estimated conversion
  uplift, not just size.

### Theme D — Reliability
- **CLI distribution** — PyPI package + `pip install shopify-image-audit`.
- **Release automation** — tag-driven release workflow.
- **Snapshot tests for the HTML report** — detect visual regressions.

---

## Out of scope (forever / for now)

- **C# extension layer** — mentioned in old roadmap; deferred indefinitely
  (Python tooling covers all needs).
- **GPU acceleration** — not relevant; the tool is I/O-bound on PageSpeed.
- **Automated image transformation** — that's a different product
  (Shopify has built-in image optimization; competing with it is wasteful).
- **Multi-store batch processing** — only relevant after Phase 3 Theme B
  proves the per-store workflow.

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

---

## Version history

| Phase | Date | Status | Tests | PRs (cumulative) |
|-------|------|--------|-------|------------------|
| 1 | 2026-03 | ✅ Complete | 103 | 16 |
| 2 | 2026-07 | ✅ Complete | 276 | 28 |
| 3 | 2026-08+ | 🔜 Planned | — | — |

See [`docs/`](.) for the full documentation tree.