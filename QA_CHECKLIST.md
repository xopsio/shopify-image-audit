
# QA Checklist (Sprint 1 + JB-002 + Sprint 2 kickoff)

**Single source of truth:** `docs/`, `schemas/`, and this `QA_CHECKLIST.md` define the contracts and rules; code must conform.

> Sprint 1 (completed, tag `v0.1.0-sprint1`) + JB-001 ValueError fix + JB-002 PageSpeed API integration merged from `origin/fix/jb001-cli-valueerror-final`.
>
> **Sprint 2 (2026-07-29):** Claude/PyCharm exited. ZCode is now coordinator and
> owns `src/engine/`, `tests/`, `src/audit/models.py`, `pyproject.toml`. See
> `docs/governance.md` v1.2. Schema-validation regression fixed (143/143 tests).

## Repo integrity
- [x] Single-writer rules followed (no cross-domain edits)
- [x] Branches updated from `origin/main` before work
- [x] No accidental new top-level folders (`src/integrations/` is intentional, per JB-002)

## CU-001 (Core)
- [x] `src/audit/parser.py` parses fixture/LHR JSON
- [x] `src/audit/ranker_heuristic.py` assigns `role`, `score (0–100)`, `recommendation`
- [x] Fixtures exist and pass pipeline expectations
- [x] `src/core/` (image_extractor + performance_scorer) integrated into pipeline and covered by `tests/test_core.py` (governance v1.2)

## WS-001 (Contracts)
- [x] `schemas/audit_result.schema.json` exists and matches v0.1 payload
- [x] `docs/spec/cli_v0_1.md` documents commands/flags/examples
- [x] `docs/runbook/measurement_protocol.md` documents measurement determinism

## JB-001 (Engine/CLI/Tests)
- [x] CLI can run on fixtures and output JSON
- [x] Pydantic models validate output (schema validation passes — see `tests/test_schema_validation.py`)
- [x] `pytest` passes locally
- [x] `--out-dir` absolute-path / `..` / prefix-bypass rejection returns exit code 2 (JB-001 fix)

## JB-002 (PageSpeed Insights API)
- [x] `src/integrations/pagespeed_api.py` implements the API client with rate-limit/error handling
- [x] CLI command `audit measure <url>` returns live LCP/CLS/INP metrics
- [x] API client tests pass with mocked responses (`tests/test_pagespeed_api.py`, 17 tests)
- [x] `pyproject.toml` updated with `requests>=2.31` (runtime) + `responses>=0.25` (dev)

## Release gate
- [x] `git diff --name-only` shows only allowed files per domain
- [x] Clean working tree before push
