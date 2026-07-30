# Sprint 3 Plan — Revenue Expansion

**Duration:** 3–4 weeks
**Status:** ✅ COMPLETE (2026-07-30)
**Phase:** Phase 3 (post-Sprint 2; see [`ROADMAP.md`](ROADMAP.md))

---

## 1. Sprint 3 Goal

Turn the manual audit-on-demand into a **product that scales**: produce
PDFs, support per-image deltas, integrate with Shopify Admin API, and ship
a PyPI package.

### Primary Objectives:
- Ship PDF export of the HTML report (enterprise customers need this)
- Add per-image before/after comparison (currently cohort-level)
- Build a Shopify Admin API client (one-shot store info + product fetch)
- Publish v0.2.0 to PyPI

### Success Criteria:
- ✅ `audit report --pdf report.pdf` produces a valid PDF
- ✅ `audit compare` shows per-image deltas (not just cohort totals)
- ✅ `audit shopify fetch <store>` retrieves store info via Admin API
- ✅ `pip install shopify-image-audit` works; `audit --version` shows 0.2.0
- ✅ All tests pass on Python 3.11 + 3.12

---

## 2. Deliverables

### DEL-1: PDF export
**Estimated:** 2–3 days

Ship `audit report <audit_result.json> --pdf report.pdf` (or
`audit compare ... --pdf comparison.pdf`). Implementation choice:
- **WeasyPrint** (preferred): mature, CSS-friendly, pure Python. Heavier
  dependency footprint (~50 MB system libs on Linux).
- **playwright/pyppeteer** (alternative): lightweight, but requires a
  Chromium install.

Recommendation: **WeasyPrint** (better CSS fidelity, easier CI install).

### DEL-2: Per-image before/after comparison
**Estimated:** 3–4 days

Currently `ComparisonResult.images` is a cohort summary
(total bytes delta, avg score delta, count). Extend it to include
**per-image deltas**: each image in the `before` snapshot paired with
its best match in `after` (by URL or src hash), with per-image byte/format/
score deltas. UI in the HTML report: a per-image table where each row shows
the image preview (or src), the bytes/score delta, and the recommendation
that resolved it.

**Open design question**: how to match images when URLs change (CDN cache
busting, query params, format conversion)? Options:
1. Match by `src` exactly (simple, breaks on `?v=2` query params)
2. Match by `(src without query, natural_width, natural_height)` (robust to
   query params but fragile to genuine duplicate URLs)
3. Match by a hash of `(src, bytes, mime)` (most robust; requires extra
   computation)

Recommendation: **option 3** for v1, fall back to option 1 when hashes
don't match (legitimate additions/removals).

### DEL-3: Shopify Admin API client
**Estimated:** 2–3 days

New module `src/integrations/shopify_admin.py`. Public API:
- `ShopifyAdminClient(shop_domain, access_token)` — constructor
- `get_shop_info()` — shop name, plan, currency
- `get_products(limit=50)` — list products with featured image URL
- `get_theme_assets()` — list theme asset URLs (for image inventory)

CLI integration:
- `audit shopify auth <shop.myshopify.com> <access_token>` — verify token
- `audit shopify inventory <shop.myshopify.com>` — list all images used

Authentication: Admin API access tokens are scoped per-app. Documentation
link in the docstring; the user provides the token explicitly (no OAuth
flow in v1).

### DEL-4: PyPI publication + v0.2.0 release
**Estimated:** 1–2 days

- Choose a final package name (`shopify-image-audit` is fine; check PyPI)
- Update `pyproject.toml`: version bump to 0.2.0, finalise dependencies,
  long description from README
- Add a release workflow (`.github/workflows/release.yml`): on tag push,
  build sdist + wheel and publish via trusted publishing (no API token)
- Tag `v0.2.0` after the previous PRs land

---

## 3. Ticket Breakdown

### TD-1: PDF export (`feat/pdf-export`)
**Owner:** ZCode
**Domain:** `src/audit/report.py`, `src/engine/cli.py`, `tests/`
**Estimated:** 2–3 days

Tasks:
1. Add `weasyprint` dependency (`pyproject.toml`)
2. Implement `_render_pdf(html_content, output_path)` in `report.py`
3. Add `--pdf` flag to `audit report` and `audit compare`
4. Write tests:
   - PDF file is created, > 0 bytes
   - PDF file starts with `%PDF` magic bytes
   - `--pdf` + `-o` produces a PDF
5. Update CI to install WeasyPrint system deps (`libpango`, `libcairo`,
   `libgdk-pixbuf`) — needs a CI workflow update

Acceptance:
- [x] `audit report foo.json --pdf report.pdf` produces a valid PDF
- [x] `audit compare before.json after.json --pdf diff.pdf` produces PDF
  with the comparison section
- [x] Tests pass with WeasyPrint installed
- [x] CI green

### TD-2: Per-image before/after comparison (`feat/per-image-deltas`)
**Owner:** ZCode
**Domain:** `src/core/baseline_manager.py`, `src/audit/models.py`, `src/audit/report.py`
**Estimated:** 3–4 days

Tasks:
1. Extend `ComparisonResult.images` to include a list of per-image deltas
2. Add `_match_images(before_imgs, after_imgs)` matching by
   `(src-stripped, bytes, mime)` hash
3. Compute per-image deltas: bytes, mime (if changed), score (before/after/delta)
4. Add a new renderer `_render_image_deltas_table()` for the HTML report
5. Tests:
   - Match by stripped src (query params ignored)
   - Missing-match handled (additions/removals tracked separately)
   - All schema fields populated; cohort summary still correct

Acceptance:
- [x] `comparison.images.per_image` is a list (even if empty)
- [x] HTML report shows per-image delta table when data available
- [x] Schema backward compatible (additions only)
- [x] Tests pass

### TD-3: Shopify Admin API client (`feat/shopify-admin`)
**Owner:** ZCode
**Domain:** `src/integrations/shopify_admin.py`, `src/engine/cli.py`
**Estimated:** 2–3 days

Tasks:
1. Implement `ShopifyAdminClient` with the three public methods
2. Add `audit shopify auth` and `audit shopify inventory` subcommands
3. Tests (with `responses` mock): successful fetch, 401, 404, rate limit
4. Docs: `docs/integrations/SHOPIFY_ADMIN.md` with token acquisition steps

Acceptance:
- [x] `audit shopify auth store.myshopify.com <token>` exits 0 with shop info
- [x] `audit shopify inventory <store>` lists all image URLs
- [x] Tests cover success + 401 + rate-limit cases

### TD-4: Release v0.2.0 to PyPI (`chore/release-v0.2.0`)
**Owner:** ZCode
**Domain:** `pyproject.toml`, `.github/workflows/release.yml`
**Estimated:** 1–2 days

Tasks:
1. Finalise `pyproject.toml` (version 0.2.0, dependencies locked, long
   description from README)
2. Add `.github/workflows/release.yml`: on `v*` tag push, build sdist +
   wheel, publish to PyPI via trusted publishing
3. Local dry-run: `python -m build && twine check dist/*`
4. Tag `v0.2.0` after TD-1/2/3 PRs land

Acceptance:
- [x] `pip install shopify-image-audit` installs v0.2.0
- [x] `audit --version` prints `shopify-image-audit 0.2.0`
- [x] Release workflow is documented

---

## 4. Acceptance Criteria (Sprint-Level)

### Business Success:
- [x] PDF report available for first customer (was a stated blocker)
- [x] Per-image deltas demonstrate ROI at per-asset granularity (vs cohort)
- [x] Shopify Admin API unlocks the "no-Lighthouse-JSON-needed" workflow

### Technical Success:
- [x] PyPI release v0.2.0 published
- [x] All new code has tests (>80% coverage maintained)
- [x] CI green on Python 3.11 + 3.12

### Quality Gates:
- [x] No regressions (276 + new tests still pass)
- [x] Docs updated: README, SPEC, ROADMAP
- [x] Ruff clean

---

## 5. Out of Scope (Sprint 3)

- ❌ Real ML model training (deferred to Phase 3 follow-up; the current
  ensemble is good enough)
- ❌ Image-optimisation automation hooks (sister tool)
- ❌ Multi-store batch processing
- ❌ Scheduled re-audits (requires infrastructure decisions)
- ❌ Branded report templates per customer
- ❌ OAuth flow for Shopify Admin (token-only in v1)

---

## 6. Timeline

### Week 1
- TD-1: PDF export

### Week 2
- TD-2: Per-image before/after comparison

### Week 3
- TD-3: Shopify Admin API client
- TD-4: Release v0.2.0 to PyPI

### Week 4 (buffer)
- Bug fixes
- Quality assurance
- Sprint 3 retrospective

---

## 7. Dependencies & Risks

### Risks

| Risk | Mitigation |
|------|------------|
| WeasyPrint system deps in CI | Use pre-built Linux wheel; or playwright fallback |
| Per-image matching too brittle | Hash-based matching + cohort fallback |
| Shopify Admin API rate limits | Use `responses` mock + plan for backoff |
| PyPI publishing requires trusted publishing setup | Document; can do manual publish if blocked |

---

## 8. Success Metrics

### Sprint KPI:
- **Ships**: 4 PRs merged
- **Tests**: 276 → ~320 tests
- **Releases**: v0.2.0 on PyPI
- **Docs**: PDF guide, Shopify Admin guide

### Long-term KPI (post-Sprint 3):
- First customer delivered via PDF report
- First audit-on-demand with no Lighthouse JSON from customer (Shopify Admin path)

---

## Next Steps
1. Review and approve this plan
2. Create GitHub issues for TD-1, TD-2, TD-3, TD-4
3. Begin TD-1 (PDF export) — smallest, highest business value

---

**Sprint 3 Start:** TBD
**Sprint 3 End:** TBD
**Retrospective:** After Sprint 3 completion