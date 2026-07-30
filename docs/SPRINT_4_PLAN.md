# Sprint 4 Plan — Scalability & Recurring Revenue

**Duration:** 3–4 weeks
**Status:** PLANNING
**Phase:** Phase 4 (post-Sprint 3; see [`ROADMAP.md`](ROADMAP.md))

---

## 1. Sprint 4 Goal

Turn the manual audit-on-demand into a product that scales to *repeat*
customers. After Sprint 3 we have a working PDF + per-image delta pipeline
and a PyPI distribution. Sprint 4 sharpens the deliverable (branding,
ROI-ranked recommendations) and starts the path to recurring engagements
(audit history + trends).

### Primary Objectives:
- Ship branded report templates (customer logo + colours)
- Order recommendations by estimated ROI (conversion uplift, not just bytes)
- Begin audit history storage so customers can see trends over time

### Success Criteria:
- `audit report --brand-logo logo.png --brand-color #ff6b35` produces a branded report
- Comparison report's `top_improvements` are ordered by ROI (highest LCP impact first)
- `audit history list mystore.myshopify.com` shows past audits with deltas
- All new code has tests (>= 80% coverage on new modules)

---

## 2. Deliverables

### DEL-1: Branded report template
**Estimated:** 2–3 days

Ship `--brand-logo <path>` and `--brand-color <hex>` flags on `audit report` (and propagate to `compare` via `-o`).

- Logo appears in the report header
- Brand colour tints the status badges, links, and header strip
- Falls back gracefully when the logo file is missing or the colour is invalid (logs warning, uses default)

### DEL-2: ROI-ranked recommendations
**Estimated:** 2 days

Replace the current `top_improvements` / `top_regressions` ordering (currently alphabetical by metric name) with ROI-based ordering.

- Each recommendation gets an estimated conversion-uplift score (LCP impact × LCP-heuristic)
- `top_improvements` is sorted by uplift, descending
- `top_regressions` similarly
- A new `recommendations` field exposes the full sorted list for clients (HTML table can render the top N)

### DEL-3: Audit history
**Estimated:** 3–4 days

Persist past `audit baseline` runs to a local history directory and add a `history` command to view trends.

- `audit baseline` records to `~/.shopify-image-audit/history/<shop-hostname>/<timestamp>.json` by default (overridable with `--history-dir`)
- `audit history list <store>` shows past audits with delta vs. latest
- `audit history show <store>` renders a trend report (HTML)
- No remote storage in v1 — local filesystem is enough for the first 99-199 € engagement
- This sets up the path for `audit history diff <store> <id1> <id2>` (deferred to Sprint 5)

---

## 3. Ticket Breakdown

### TD-1: Documentation & tech-debt cleanup
**Owner:** ZCode
**Domain:** `docs/`, `.gitignore`, stale GitHub issues
**Estimated:** 1 day

Tasks:
1. Update README: badge counts, roadmap, broken file references
2. Update ROADMAP: mark Phase 3 done, add Sprint 4 themes
3. Update `docs/SPRINT_3_PLAN.md`: mark complete
4. Update `docs/spec/cli_v0_1.md`: add `version` command, `--pdf` flag, `shopify` command
5. Add `.gitignore` entries for `build/lib/`, IDE files, OS files
6. Close 8 stale issues (#2, #3, #4, #11, #12, #13, #14, #16)

Acceptance:
- [x] All docs match the code (no broken references)
- [x] ROADMAP, README, SPRINT_3_PLAN agree on Sprint 3 status
- [x] Spec lists every actual CLI command
- [x] 8 stale issues closed with rationale

### TD-2: Branded report template
**Owner:** ZCode
**Domain:** `src/audit/report.py`, `src/engine/cli.py`
**Estimated:** 2–3 days

Tasks:
1. New helpers in `report.py`: `_render_header(audit_result, *, brand_logo_b64, brand_color)` that produces a header strip with the brand colour
2. New CSS variables in `_CSS` for `--brand-color` and `--brand-accent`; badges use `var(--brand-accent)` so a single flag changes them all
3. New CLI flag `--brand-logo <path>` on `audit report` (and `audit compare -o`). Path is validated like other output paths (must be relative + within cwd)
4. New CLI flag `--brand-color <hex>` (e.g. `--brand-color "#ff6b35"`)
5. Logo is loaded and base64-encoded; embedded in the HTML so the report is self-contained (no external file dependency)
6. Missing logo / invalid colour → warning printed, default styling used

Acceptance:
- [ ] `audit report foo.json --brand-logo logo.png --brand-color "#ff6b35" -o branded.html` produces a report with the brand colour in the header
- [ ] `audit report foo.json` (no brand args) still works (no regression)
- [ ] Tests for the brand-colour parser, the base64 encoding, and the CSS rendering
- [ ] Bad colour / missing logo paths log a clear warning and fall back

### TD-3: ROI-ranked recommendations
**Owner:** ZCode
**Domain:** `src/core/baseline_manager.py`, `src/audit/models.py`
**Estimated:** 2 days

Tasks:
1. New `ComparisonRecommendation` model: `text: str`, `category: str` (e.g. `image_conversion`, `lcp_heavy`, `format_modern`), `estimated_lcp_impact_ms: float`, `sort_key: float` (ROI impact score, higher = better for improvements, lower = worse for regressions)
2. `compare()` builds a list of `ComparisonRecommendation` objects from the deltas, then sorts them by `sort_key` (improvements: descending, regressions: ascending)
3. `summary.top_improvements` / `top_regressions` now reflect the ROI-ordered list
4. New `summary.recommendations` field exposes the full sorted list (the existing fields are kept for backward compat — they're now derived from the same list)
5. HTML report uses the new ordering automatically

Acceptance:
- [ ] `summary.recommendations` is a list of `ComparisonRecommendation` with `sort_key` populated
- [ ] `summary.top_improvements[0]` is the highest-ROI improvement
- [ ] `summary.top_regressions[0]` is the worst-ROI regression
- [ ] HTML report still shows the same content (or richer) and the test suite still passes
- [ ] Tests for the sort order across multiple improvement/regression scenarios

### TD-4: Audit history
**Owner:** ZCode
**Domain:** `src/engine/cli.py`, new `src/engine/history.py`, new `audit history` command
**Estimated:** 3–4 days

Tasks:
1. New module `src/engine/history.py`:
   - `HistoryStore(base_dir)` — manages `~/.shopify-image-audit/history/<hostname>/<ts>.json` files
   - `record(audit_result: AuditResult, *, label: str | None)` — saves a snapshot
   - `list_entries(hostname: str) -> list[HistoryEntry]` — returns sorted-by-time
   - `latest(hostname: str) -> HistoryEntry | None`
2. `audit baseline` records the result via `HistoryStore` (alongside the existing `--save` flag)
3. New `audit history` subcommand with `list` and `show` sub-subcommands
4. `audit history list mystore.myshopify.com` — prints a table of past audits
5. `audit history show mystore.myshopify.com` — generates a trend HTML (uses existing report infrastructure)

Acceptance:
- [ ] `audit baseline foo.json --save baseline.json` records a copy to `~/.shopify-image-audit/history/<host>/<ts>.json` (alongside the user-supplied path)
- [ ] `audit history list mystore.myshopify.com` lists recorded audits
- [ ] `audit history show mystore.myshopify.com` produces a trend HTML
- [ ] `--history-dir <path>` overrides the default location
- [ ] Tests use `tmp_path` for the history directory

---

## 4. Acceptance Criteria (Sprint-Level)

### Business Success:
- [ ] Branded reports can be delivered to enterprise customers (logo + brand colour)
- [ ] Recommendations are ordered by ROI so the most impactful ones appear first
- [ ] Repeat customers can see audit trends over time

### Technical Success:
- [ ] Audit history persists across runs
- [ ] All new code has tests (>= 80% coverage on new modules)
- [ ] `cli.py` coverage improves (currently 63%)

### Quality Gates:
- [ ] No regressions (390 + new tests still pass)
- [ ] Ruff clean
- [ ] CI green Python 3.11 + 3.12
- [ ] Docs updated: README, SPRINT_4_PLAN, ROADMAP, CLI spec

---

## 5. Out of Scope (Sprint 4)

- ❌ Remote storage (S3, GCS) — local filesystem only in v1
- ❌ `audit history diff <id1> <id2>` — deferred to Sprint 5
- ❌ Scheduled re-audit (cron/Cloud scheduler) — deferred; needs infrastructure decisions
- ❌ Real ML model training — explicitly out of scope per decision log
- ❌ Image-optimisation automation hooks (sister tool)
- ❌ Branded CSS templates per customer (custom HTML themes) — beyond colour+logo

---

## 6. Timeline

### Week 1
- TD-1: Documentation cleanup + stale issue close (1 day)
- TD-2: Branded report template (start)

### Week 2
- TD-2: Branded report template (complete + tests)
- TD-3: ROI-ranked recommendations (start)

### Week 3
- TD-3: ROI-ranked recommendations (complete)
- TD-4: Audit history (start)

### Week 4
- TD-4: Audit history (complete + tests)
- Sprint 4 retrospective
- v0.3.0 release prep (PR + tag)

### Week 5 (buffer)
- Bug fixes, retrospective, v0.3.0 release

---

## 7. Dependencies & Risks

### Risks

| Risk | Mitigation |
|------|------------|
| Brand-colour CSS breaks existing report layout | Visual snapshot tests; fall back to default on any render failure |
| `~/.shopify-image-audit/` ownership on shared systems | Respect `$XDG_DATA_HOME`; allow `--history-dir` override |
| History storage grows unbounded | Cap at last 100 entries per hostname; prune in `record()` |
| Logo file path security | Reuse existing `validate_out_path()`-style checks |
| ROI heuristic oversimplified | Document as heuristic; add source comment in `_build_summary()` |

---

## 8. Success Metrics

### Sprint KPI:
- 4 PRs merged (TD-1, TD-2, TD-3, TD-4)
- ~50–60 new tests
- Total tests: 390 → ~440–450
- v0.3.0 release prep
- `cli.py` coverage: 63% → ~75%

### Long-term KPI (post-Sprint 4):
- Branded report can be a paid upgrade tier
- Audit history enables monthly audit subscriptions
- Lower CAC for repeat customers (they have a baseline)

---

## Next Steps
1. Review and approve this plan
2. Create GitHub issues for TD-1..TD-4
3. Begin TD-1 (docs cleanup)
