# Changelog

All notable changes to **shopify-image-audit** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Empty — all Sprint 8 work shipped in v0.7.0.

---

## [0.7.0] - 2026-07-31

### Added (Sprint 8)
- "Did you mean: X?" suggestions on every CLI typo site (`--device`,
  `--strategy`, `--ranker`, shopify/history/schedule subcommands) via
  `difflib.get_close_matches` — TD-1
- `audit schedule run-all --parallel <N>` (deferred from Sprint 7; now
  trivial thanks to the shared `run_parallel` helper) — TD-3
- Shared `src/engine/_parallel.py::run_parallel(items, fn, *, parallel,
  stop_on_error, cancelled_factory)` is now the single concurrency
  primitive for `run_batch` and `run_all_schedules` — TD-3
- `tests/conftest.py` + `tests/__init__.py`: single source of truth for
  shared `REPO_ROOT`, `FIXTURES`, `cli_runner`, `sample_audit_result`,
  `populated_history_dir` — TD-2
- `pip install shopify-image-audit` no longer pulls WeasyPrint; PDF
  export moved to optional `[pdf]` extra (`shopify-image-audit[pdf]`)
  — TD-4
- `src/audit/report.py::render_pdf_report` raises a friendly
  `ImportError` with install instructions when WeasyPrint is missing
  — TD-4
- `docs/tutorial.md` — 6-step "from install to delivered report in <5min"
  walkthrough — TD-4
- `MANIFEST.in` (NEW) ships CHANGELOG, CONTRIBUTING, README (note:
  schemas/docs ship via PyPI sdist only — wheel packaging of those is
  deferred to Sprint 9 because setuptools.package-data is finicky) — TD-4

### Changed
- Test files: removed 8 duplicated `REPO_ROOT` declarations, 6 stale
  `sys.path.insert()` calls — TD-2
- `fixtures/` and `tests/fixtures/` consolidated (was inconsistent —
  `test_core` pointed elsewhere) — TD-2

### Stats
- 665 tests pass (up from 656)
- Ruff clean
- Single concurrency primitive (`run_parallel`) replaces two copies
- Test fixtures consolidated into one place

[0.7.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/xopsio/shopify-image-audit/compare/v0.6.0...v0.6.1

---

## [0.6.1] - 2026-07-31

### Fixed
- `_version.py` was not shipped in the wheel (`packages.find` didn't
  discover bare top-level modules). Added `[tool.setuptools]
  py-modules = ["_version"]`; verified to appear in `RECORD`.
- `_version.get_version()` now reads `importlib.metadata.version()` as
  primary path (works for pip/pipx/wheel installs), with `pyproject.toml`
  parsing as a development-checkout fallback, then `"unknown"`.
- `--no-cache` flag was documented but unimplemented on `audit measure`
  and `audit compare`. Flag added; `ResponseCache` plumbed through
  `fetch_url_as_audit()` and `fetch_lighthouse_json()`. Live-URL CLI
  tests updated to pass `--no-cache` to avoid cross-test cache leakage.
- `CHANGELOG.md` had two `[Unreleased]` reference definitions; removed
  the stale one.

### Stats
- 642 tests pass (no regression)
- Ruff clean

[Unreleased]: https://github.com/xopsio/shopify-image-audit/compare/v0.6.1...HEAD
[0.6.1]: https://github.com/xopsio/shopify-image-audit/compare/v0.6.0...v0.6.1

---

## [0.4.0] - 2026-07-30

### Added (Sprint 5)
- Snapshot testing infrastructure (syrupy) — 22 golden files covering 9 deterministic HTML renderers — TD-1
- CLI coverage close-out: every one of the 10 Typer commands now has at least one happy-path test in `tests/test_cli.py` / `tests/test_cli_coverage.py` — TD-2
- `audit history diff <store> --from <id> --to <id>` — diff any two historical snapshots and emit a comparison HTML — TD-4
- Stable `HistoryEntry.id` (12-char SHA-256 prefix of snapshot bytes, independent of filename/timestamp)
- `HistoryStore.get_by_id(hostname, id)` and `HistoryStore.compare_entries(hostname, id_a, id_b)` primitives
- `generate_diff_html(hostname, entry_a, entry_b, comparison)` — diff renderer with vitals table, image-stats table, ROI summary
- `validate_out_path()` now applied to `_history_show` and `_history_diff` `--output` flags (DX polish)
- `CHANGELOG.md` (this file)
- `--cov-fail-under=85` enforced in CI (current coverage: 91.24%)

### Changed
- All inline `try/except` boilerplate in `cli.py` replaced with the documented error decorators (`@handle_pipeline_errors`, `@handle_compare_errors`, `@handle_json_errors`, new `@handle_shopify_errors`) — `-58` lines net
- `RuntimeError` exit code now consistently **10** across all commands (was: 2 in `extract`/`score`/`report`/`shopify`)
- `cli.py` `809 → 751` lines

### Stats
- 546 tests (up from 489)
- 91.24% coverage (above 85% threshold)
- Ruff clean
- Trusted publishing on PyPI

[0.4.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.1.0-sprint1...v0.2.0
[0.1.0]: https://github.com/xopsio/shopify-image-audit/releases/tag/v0.1.0-sprint1

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

## [0.5.0] - 2026-07-30

### Added (Sprint 6)
- `audit shopify batch --stores-file <path>` — multi-store inventory audit with `--parallel N` (concurrent workers) and `--stop-on-error` flag — TD-3
- `src/engine/batch.py` (NEW): `StoreConfig`, `parse_stores_file`, `run_batch`, `merge_inventory`
- `src/engine/_logging.py` (NEW, ~70 lines): centralised `logging.getLogger("shopify_image_audit")` with `LOG_LEVEL` env-var override — TD-4
- 6 structured log hooks (INFO at request, DEBUG per stage/branch, ERROR on subprocess failure) across `audit_orchestrator`, `engine.history`, `pagespeed_api`, `_run_lighthouse`, brand validators, role sanitiser
- `CONTRIBUTING.md` (NEW, ~150 lines): WeasyPrint install + snapshot workflow + release process + observability guide
- `tests/test_table_snapshots.py` (NEW, 16 tests): Rich Console captures for `_table.py` renderers — TD-1

### Changed
- CI coverage threshold: `--cov-fail-under=85` → `--cov-fail-under=90`
- Test isolation: zero `Path("foo")` writes or `os.chdir` in tests; all CLI output writes go through `tmp_path` or `monkeypatch.chdir` — TD-2
- `HistoryStore._prune()` now returns the prune count (was: `None`)

### Stats
- 606 tests (up from 546)
- 93% coverage (up from 91.24%)
- `_table.py` coverage 68% → 100%
- Ruff clean

---

## [0.6.0] - 2026-07-30

### Added (Sprint 7)
- `audit schedule list/add/remove/run-all` — scheduled re-audit via the
  external-cron model (Sprint 4's deferred work, finally shipped) — TD-1
- `src/engine/scheduler.py` (NEW): ScheduleConfig, ScheduleStore,
  run_all_schedules — reads `~/.shopify-image-audit/schedules.json` and
  records each fetch to `HistoryStore`
- `src/integrations/_cache.py` (NEW): on-disk PageSpeed response cache with
  TTL — `PAGESPEED_CACHE_TTL` env var (default 3600s; `0` disables) — TD-3
- `src/_version.py` (NEW): shared `get_version()` helper — fixes the
  long-standing report footer version drift (was hardcoded `v0.1`)
- `docs/runbook/scheduled_reaudit.md` (NEW): crontab snippet, systemd
  timer alternative, `flock` overlap-prevention, env-var reference, security
  notes, troubleshooting
- Dependabot config (`.github/dependabot.yml`) — weekly pip + GitHub
  Actions updates with grouped minor+patch — TD-2
- SLSA build-provenance attestation on every PyPI release (best-effort,
  non-blocking) — TD-2

### Changed
- CLI spec (`docs/spec/cli_v0_1.md`) rewritten to document all 11 actual
  commands (was: 8) — TD-4
- `README.md`: added `pipx install` Deployment section, fixed test-count
  drift (3 different numbers → 1 consistent), added Lighthouse CLI
  prerequisite note
- `docs/runbook/measurement_protocol.md`: corrected the `--runs`
  semantics (last run, not median) — TD-4
- Runtime deps: upper caps on `pydantic`, `typer`, `rich`, `requests`,
  `jsonschema` (matches existing `weasyprint` pinning pattern) — TD-2

### Stats
- 642 tests (up from 606)
- Ruff clean
- Trusted publishing + provenance attestation active for PyPI

[0.6.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/xopsio/shopify-image-audit/compare/v0.1.0-sprint1...v0.2.0
[0.1.0]: https://github.com/xopsio/shopify-image-audit/releases/tag/v0.1.0-sprint1