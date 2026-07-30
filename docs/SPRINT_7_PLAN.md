# Sprint 7 Plan — Scheduled Re-audit, Dependency Hygiene & Report Polish

**Duration:** ~2 weeks
**Status:** ✅ COMPLETE (v0.6.0 released 2026-07-30)
**Phase:** Phase 7 (complete; see [`ROADMAP.md`](ROADMAP.md))

---

## 1. Sprint 7 Goal

Ship the long-deferred scheduled re-audit (external cron model), add
dependency hygiene (Dependabot + provenance + PageSpeed response cache),
polish the report footer/version drift, and update the stale CLI spec
docs.

### Success Criteria
- `audit schedule run-all` reads `~/.shopify-image-audit/schedules.json`,
  runs audits for each configured store, and records results to history
- A documented cron snippet for `crontab -e` shows how to schedule
  daily/weekly re-audits
- Dependabot is enabled (weekly Python + GitHub Actions updates)
- PyPI releases carry SLSA build-provenance attestations
- PageSpeed responses are cached on disk (TTL-configurable)
- Report footer shows the real version (not hardcoded `v0.1`)
- CLI spec doc lists all 11 actual commands

---

## 2. Deliverables

### DEL-1: Scheduled re-audit (TD-1) ✅
- `src/engine/scheduler.py` (NEW): ScheduleConfig, ScheduleStore, run_all_schedules
- `src/engine/cli.py`: new `audit schedule list/add/remove/run-all` subcommand
- `tests/test_scheduler.py` (NEW, 24 tests)
- `docs/runbook/scheduled_reaudit.md` (NEW): crontab + systemd timer + flock

### DEL-2: Dependency hygiene (TD-2) ✅
- `.github/dependabot.yml` (NEW): weekly pip + github-actions
- `.github/workflows/release.yml`: SLSA build-provenance attestation
- `pyproject.toml`: upper caps on runtime deps

### DEL-3: PageSpeed cache + report footer fix (TD-3) ✅
- `src/integrations/_cache.py` (NEW): ResponseCache with TTL
- `src/integrations/pagespeed_api.py`: client consults cache
- `src/_version.py` (NEW): shared get_version() helper
- `src/audit/report.py`: footer shows real version

### DEL-4: Docs polish + v0.6.0 release (TD-4) ✅
- `docs/spec/cli_v0_1.md`: rewrite to document all 11 commands
- `README.md`: Deployment section (pipx), Lighthouse CLI prerequisite,
  test-count drift fixed
- `docs/runbook/measurement_protocol.md`: corrected `--runs` semantics
- v0.6.0 released to PyPI

---

## 3. Acceptance Criteria

### Quality Gates:
- [x] Total coverage ≥90% (enforced)
- [x] 642 tests pass (up from 606)
- [x] Ruff clean
- [x] CI green Python 3.11 + 3.12
- [x] v0.6.0 released to PyPI

---

## 4. Stats Summary

| Metric | v0.5.0 | v0.6.0 | Δ |
|--------|--------|--------|---|
| Tests | 606 | 642 | +36 |
| Coverage | 91.39% | 91%+ | — |
| CLI commands | 11 | 12 | +1 (schedule) |
| Dependabot | ❌ | ✅ | new |
| SLSA provenance | ❌ | ✅ | new |
| PageSpeed cache | ❌ | ✅ | new |

---

See [`CHANGELOG.md`](../CHANGELOG.md) for the full release log.