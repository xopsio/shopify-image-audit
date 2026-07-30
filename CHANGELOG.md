# Changelog

All notable changes to **shopify-image-audit** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned for v0.4.0 (Sprint 5)

- Snapshot testing infrastructure (syrupy) for HTML renderers — TD-1
- CLI coverage close-out for all 10 commands — TD-2
- Error decorator wiring (`@handle_pipeline_errors`, `@handle_compare_errors`, `@handle_json_errors`, `@handle_shopify_errors`) + consistency pass — TD-3
- `audit history diff <store> --from <id> --to <id>` command with stable entry-ids — TD-4
- `CHANGELOG.md` (this file) — TD-4
- CI coverage threshold (`--cov-fail-under=85`) — TD-4

---

## [0.3.0] - 2026-07-30

### Added (Sprint 4)
- Branded report templates — `--brand-logo <path>` and `--brand-color <hex>` on `audit report` and `audit compare -o`
- ROI-ranked recommendations — new `ComparisonRecommendation` model with `sort_key` based on estimated conversion uplift; improvements sorted descending by ROI, regressions ascending
- Audit history storage — `HistoryStore` records each `audit baseline` to `~/.local/share/.shopify-image-audit/history/<hostname>/`
- `audit history list <hostname>` — Rich table of past audits
- `audit history show <hostname>` — trend HTML report
- `--history-dir <path>` and `--label <text>` flags on `audit baseline`
- PDF rendering hardened — restricted URL fetcher (data: only) for safer PDFs
- WeasyPrint constrained to `>=69.0,<70` for reproducibility

### Changed
- `ComparisonSummary` now has a structured `recommendations` field (backward-compatible `top_improvements`/`top_regressions` derived from it)
- Baseline command auto-records to audit history; failures are warnings, not errors

### Stats
- 489 tests (up from 390)
- Ruff clean
- Trusted publishing active for PyPI (`xopsio/shopify-image-audit`)

---

## [0.2.0] - 2026-07-30

### Added (Sprint 3)
- PDF export via `--pdf` flag (`audit report --pdf`, `audit compare -o foo.html --pdf`)
- Per-image before/after deltas with 2-phase matching (hash + src fallback)
- Shopify Admin API integration: `audit shopify auth` and `audit shopify inventory`
- v0.2.0 release prep: trusted publishing, hardened release workflow
- Structural build/publish split in release workflow (job-level if instead of shell dry_run)
- `workflow_dispatch` trigger on release workflow for manual dry runs

### Stats
- 390 tests (up from 276)
- 4 PRs merged (TD-1 through TD-4)

---

## [0.1.0] - 2026-07-29

### Added (Sprints 1 + 2)
- `audit run <url>` — full Lighthouse + audit pipeline
- `audit extract <lighthouse.json>` — image + LCP feature extraction
- `audit score <audit_input.json> --ranker {heuristic|ml}` — image scoring with two rankers
- `audit report <audit_result.json>` — HTML report generation
- `audit measure <url>` — live PageSpeed Insights metrics
- `audit baseline <lhr.json> --save <path>` — capture reusable baseline
- `audit compare <baseline> <current>` — before/after comparison (file or URL)
- PageSpeed Insights integration with rate-limit handling
- Pydantic v2 models with JSON schema contract (`schemas/audit_result.schema.json`)
- ML-style ranker (`audit.ranker_ml`) — hand-coded weighted ensemble
- CI workflow (Python 3.11 + 3.12, ruff, pytest-cov)
- Branch protection on `main`
- Customer report template + onboarding guide

### Stats
- 276 tests at end of Sprint 2
- 8 issues closed as superseded
- 30+ merged PRs

---

[Unreleased]: https://github.com/xopsio/shopify-image-audit/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.1.0-sprint1...v0.2.0
[0.1.0]: https://github.com/xopsio/shopify-image-audit/releases/tag/v0.1.0-sprint1