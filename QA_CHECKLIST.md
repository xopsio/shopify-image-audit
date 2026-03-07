
# QA Checklist (Sprint 1)

**Single source of truth:** `docs/`, `schemas/`, and this `QA_CHECKLIST.md` define the contracts and rules; code must conform.

## Repo integrity
- [ ] Single-writer rules followed (no cross-domain edits)
- [ ] Branches updated from `origin/main` before work
- [ ] No accidental new top-level folders

## CU-001 (Core)
- [ ] `src/audit/parser.py` parses fixture/LHR JSON
- [ ] `src/audit/ranker_heuristic.py` assigns `role`, `score (0–100)`, `recommendation`
- [ ] Fixtures exist and pass pipeline expectations

## WS-001 (Contracts)
- [ ] `schemas/audit_result.schema.json` exists and matches v0.1 payload
- [ ] `docs/spec/cli_v0_1.md` documents commands/flags/examples
- [ ] `docs/runbook/measurement_protocol.md` documents measurement determinism

## JB-001 (Engine/CLI/Tests)
- [ ] CLI can run on fixtures and output JSON
- [ ] Pydantic models validate output (or schema validation passes)
- [ ] `pytest` passes locally

## Release gate
- [ ] `git diff --name-only` shows only allowed files per domain
- [ ] Clean working tree before push
'@ | Set-Content -Encoding UTF8 .\QA_CHECKLIST.md