# Sprint 5 Plan — Reliability & Developer Experience

**Duration:** ~2 weeks
**Status:** ✅ COMPLETE (v0.4.0 released 2026-07-30)
**Phase:** Phase 5 (complete; see [`ROADMAP.md`](ROADMAP.md))

---

## 1. Sprint 5 Goal

Sprint 4 expanded the surface area (brand templates, ROI recs, history). Sprint 5 **locks it down** — every existing renderer gets a snapshot baseline, every CLI command gets an integration test, every inline `try/except` boilerplate gets replaced with the existing-but-unused error decorators, and the deferred `audit history diff` command ships.

### Success Criteria
- HTML report & trend HTML changes are caught by snapshot tests on every PR
- All 10 CLI commands have at least one happy-path test in `tests/test_cli.py`
- `cli.py` error handling flows through the documented decorator API
- `audit history diff <store> --from <id> --to <id>` works end-to-end with a comparison report
- `--cov-fail-under=85` enforced in CI
- `CHANGELOG.md` exists and documents all released versions

---

## 2. Deliverables

### DEL-1: Snapshot test infrastructure (TD-1)
**Status:** ✅ DONE

22 golden files cover 9 deterministic render functions (`_render_head`, `_render_vitals`, `_render_stats`, `_render_image_table`, `_render_role_distribution`, `_render_comparison_section`, `_render_per_image_deltas`, `_render_footer`, `generate_trend_html`).

### DEL-2: CLI coverage close-out (TD-2)
**Status:** ✅ DONE

All 10 Typer commands now have happy-path CLI tests in `tests/test_cli_coverage.py` and `tests/test_cli.py`. Added `TestVersionCommand`, `TestMeasureCommand`, `TestExtractCommand`, `TestScoreCommand`, `TestHistoryCliDispatcher`, `TestBaselineRecordsHistory`.

### DEL-3: Wire error decorators + consistency pass (TD-3)
**Status:** ✅ DONE

All 4 decorators in `engine.cli_helpers._errors` now have at least 1 caller. `cli.py` dropped from 809 → 751 lines. `RuntimeError` consistently maps to exit 10 across all commands.

### DEL-4: `audit history diff` + DX polish (TD-4)
**Status:** ✅ DONE

Stable `HistoryEntry.id`, `HistoryStore.get_by_id()`, `HistoryStore.compare_entries()`, `audit history diff` CLI subcommand, `generate_diff_html()`, `CHANGELOG.md`, `--cov-fail-under=85` in CI.

---

## 3. Acceptance Criteria (Sprint-Level)

### Business Success:
- [x] Visual regressions in HTML report catch CI on every PR
- [x] Repeat customers can diff any two historical audits
- [x] Coverage regression is caught by CI

### Technical Success:
- [x] Snapshot infrastructure in place for future renderers
- [x] `cli.py` is shorter and more consistent (every command uses the decorator API)
- [x] CHANGELOG.md is the canonical release log

### Quality Gates:
- [x] No regressions (489 existing tests + 57 new = 546 pass)
- [x] Ruff clean
- [x] Coverage ≥ 85% (enforced; actual 91.24%)
- [x] CI green Python 3.11 + 3.12
- [x] Docs updated: README, ROADMAP

---

## 4. Out of Scope (Sprint 5)

- ❌ Scheduled re-audit (cron/Cloud scheduler) — needs infra decisions (deferred to Sprint 6)
- ❌ Multi-store batch processing — only relevant after per-store workflow proves
- ❌ Real ML model training — explicit out of scope per decision log
- ❌ Image-optimisation automation hooks (sister tool)
- ❌ OAuth flow for Shopify Admin — token-only in v1
- ❌ Branded CSS templates per customer (custom HTML themes) — beyond colour+logo
- ❌ Real-time progress bars for Lighthouse runs (cosmetic)

---

## 5. Next Steps

1. ✅ Approve this plan
2. ✅ Create GitHub issues for TD-1..TD-4
3. ✅ TD-1 → TD-2 → TD-3 → TD-4 merged
4. ✅ v0.4.0 released to PyPI

Sprint 5 is closed. See [`CHANGELOG.md`](../CHANGELOG.md) for the full release log.