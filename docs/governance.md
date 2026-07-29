# Governance & Domain Ownership

**Last updated:** 2026-07-30 (Single-agent model — all worker bots exited)
**Project:** shopify-image-audit
**Model:** Single-agent development (ZCode owns everything)

---

## Overview

This project is developed by a **single agent: ZCode**, which owns every
domain — specification, core algorithms, engine/CLI, integrations, tests, and
packaging. There is no multi-agent handoff; the "single-writer" concern from
earlier governance versions collapses into a single owner of the whole tree.

> **Governance history:** the project began as a 3×3 multi-agent model
> (Claude/JetBrains, Cursor/Grok, Windsurf/ChatGPT). Claude/PyCharm exited at
> Sprint 2 (v1.2). As of v1.3, Cursor/Grok and Windsurf/ChatGPT have also
> exited; **ZCode now owns the entire codebase**. The historical authorship
> record is preserved in the Sprint 1 post-mortem below for traceability.

---

## Domain Ownership (all ZCode)

All directories are owned by ZCode:

| Path | Purpose |
|------|---------|
| `src/audit/` | models, parser, rankers, report, lighthouse_runner |
| `src/core/` | image_extractor, performance_scorer, (baseline_manager planned) |
| `src/engine/` | CLI, audit_orchestrator |
| `src/integrations/` | pagespeed_api |
| `tests/` | the entire test suite + fixtures |
| `schemas/` | JSON schema data contracts |
| `docs/` | specifications, runbooks, governance |
| `fixtures/` | shared fixture data |
| `pyproject.toml` | packaging, dependencies, build config |
| `QA_CHECKLIST.md` | quality gates and acceptance criteria |

**Responsibilities:**
- All feature implementation across every domain
- Schema ↔ Pydantic ↔ output contract
- The full test suite (determinism / reproducibility)
- CLI interface (run, extract, score, report, measure, baseline, compare)
- Packaging, CI, releases
- Reviewing and merging own PRs

---

## Workflow

With a single owner the PR model simplifies, but we still keep a branching +
review discipline so each change is verified before it lands on `main`:

1. Implement on a feature/fix branch (`feat/<topic>` / `fix/<topic>` / `refactor/<topic>`)
2. Verify: tests pass, lint clean, behaviour-preserving where applicable
3. Open a PR against `main`
4. Review the full diff, run the test suite
5. Squash-merge when tests and acceptance criteria pass
6. Sync local `main`, delete the branch (local + remote)

### Commit / PR conventions
- Commit title: `<TYPE>: <description> (#issue)`
  - Types: `FEAT`, `FIX`, `REFACTOR`, `DOCS`, `CHORE`, `TEST`
- Reference the issue number in the PR title/body and commit message
- Update the linked issue with a status comment on merge

---

## File Organization (Current State)

```text
shopify-image-audit/
├── src/
│   ├── audit/          # models, parser, ranker_heuristic, ranker_ml,
│   │                   # report, lighthouse_runner   (all ZCode)
│   ├── core/           # image_extractor, performance_scorer  (all ZCode)
│   ├── engine/         # cli, audit_orchestrator              (all ZCode)
│   └── integrations/   # pagespeed_api                       (all ZCode)
├── tests/              # full suite + fixtures                (all ZCode)
├── schemas/            # audit_result.schema.json             (all ZCode)
├── docs/               # specs, runbooks, governance          (all ZCode)
├── fixtures/           # fixture data                         (all ZCode)
└── pyproject.toml                                            (all ZCode)
```

---

## Quality Gates

### Before Merge to Main

- [ ] All tests pass (currently 179/179)
- [ ] Pydantic models validate against `schemas/audit_result.schema.json`
- [ ] CLI commands work end-to-end
- [ ] `ruff` clean on changed files
- [ ] Behaviour-preserving refactors verified against a golden/baseline output
- [ ] No regressions

---

## Sprint 1 Post-Mortem (Historical)

The original 3×3 model assigned work to Claude/JetBrains, Cursor/Grok, and
Windsurf/ChatGPT. In practice Sprint 1 skewed heavily toward Claude/JetBrains
(82.2% of the codebase) because `src/audit/` was unassigned and Claude filled it
by necessity. As of v1.3 all worker agents have exited; ZCode owns everything.

| Domain | Planned | Actual Sprint 1 | Note |
|--------|---------|-----------------|------|
| Claude/JetBrains | ~40% | 82.2% (1,982 lines) | Exited Sprint 2 (v1.2) |
| Cursor/Grok | ~40% | 16.2% (302 lines) | Exited v1.3 |
| Windsurf/ChatGPT | ~20% | 1.6% | Exited v1.3 |

Sprint 2 onward: **ZCode (single owner) — 100%.**

---

## Version History

| Version | Date       | Changes                                                                                  |
| ------- | ---------- | ---------------------------------------------------------------------------------------- |
| 1.0     | 2026-03-01 | Initial 3×3 model definition                                                             |
| 1.1     | 2026-03-08 | Post Sprint 1: formalize `src/audit/` ownership, clarify ownership vs. authorship        |
| 1.2     | 2026-07-29 | Sprint 2: Claude/PyCharm exit; ZCode becomes coordinator + absorbs engine/tests/models   |
| 1.3     | 2026-07-30 | Single-agent model: Cursor/Grok and Windsurf/ChatGPT exit; ZCode owns the entire project |

---

## References

- See `archive/sprint1-analysis/CLAUDE_DOMAIN_REPORT.md` for detailed code analysis
- See `docs/SPRINT_1_COMPLETE.md` for Sprint 1 completion summary
- See `docs/SPRINT_2_PLAN.md` for the active sprint plan
