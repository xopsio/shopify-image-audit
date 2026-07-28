# Governance & Domain Ownership

**Last updated:** 2026-07-29 (Sprint 2 kickoff — Claude/PyCharm exit)
**Project:** shopify-image-audit
**Model:** Multi-agent development with a coordinator

---

## Overview

This project is developed by multiple AI agents working in parallel, each owning
specific domains. **ZCode acts as coordinator** and also owns the backend /
engine / test domains. This document defines ownership boundaries,
responsibilities, and integration protocols.

> **Sprint 2 governance change:** Claude/PyCharm is no longer on the project.
> Its domains (`src/engine/`, `tests/`, `pyproject.toml`, `src/audit/models.py`)
> are absorbed by **ZCode (coordinator)**. The three remaining worker agents
> continue with their core domains. See Sprint 1 post-mortem below for the
> historical authorship picture.

---

## Domain Ownership

### ZCode (Coordinator + Backend & Testing)

**Role:** Coordinator of the whole project; merges PRs, writes issues, keeps the
build green, integrates components from the worker agents.

**Owned Domains:**
- `src/engine/` — Orchestration, CLI, pipeline integration
- `src/audit/models.py` — Pydantic v2 data models (the serialization contract)
- `tests/` — All test files, test harness, fixtures (single-writer for determinism)
- `pyproject.toml` — Packaging, dependencies, build configuration

**Responsibilities:**
- Orchestrator pipeline implementation
- CLI interface (run, extract, score, report, measure, baseline, compare)
- Data model validation and the schema ↔ Pydantic contract
- Single-writer test suite (determinism / reproducibility)
- Integration of core components from other domains
- Packaging, CI, and release configuration
- Reviewing and merging PRs; splitting work into issues

---

### Cursor/Grok (Core Algorithms)

**Owned Domains:**
- `src/core/` — Core algorithms, extractors, scorers
- `src/audit/parser.py` — Lighthouse JSON parser (migrating to `src/core/`)
- `src/audit/ranker_heuristic.py` — Heuristic scoring algorithm
- New scoring modules (e.g. baseline manager, comparison engine)

**Responsibilities:**
- Image extraction from Lighthouse JSON
- Performance scoring algorithms (heuristic v1, ML-based planned for Phase 3)
- Feature engineering for scoring
- Baseline capture / delta calculation / before-after comparison engine
- Algorithm optimization
- Provide fixtures + expected outputs for all code paths

---

### Windsurf/ChatGPT (Specification & Documentation)

**Owned Domains:**
- `schemas/` — JSON schemas, data contracts
- `docs/` — Specifications, runbooks, documentation
- `QA_CHECKLIST.md` — Quality gates, acceptance criteria
- `src/audit/report.py` — HTML report generation (shared with coordinator)

**Responsibilities:**
- Schema definitions (`audit_result.schema.json`)
- CLI specifications and runbooks
- Measurement protocols and determinism rules
- Quality assurance criteria and release gates
- Customer-facing documentation (report templates, onboarding guides)

---

## Single-Writer Rule

**Critical Principle:** Each folder/file has exactly ONE owner.

### Why This Matters
- **Determinism:** Tests must be reproducible (ZCode is the single test-writer)
- **Conflict Avoidance:** No merge conflicts within a domain
- **Clear Accountability:** Each domain owns its outputs

### How It Works
1. Domain owner implements a feature in its folder, on a feature branch
2. Domain owner opens a PR with the implementation
3. ZCode (coordinator) reviews, writes/integrates tests, merges
4. If another agent needs changes → open an issue against the owning domain,
   do **not** edit directly

---

## Integration Protocol

### Cross-Domain Dependencies

**Example: ZCode integrates Cursor-authored parser**
```python
# src/engine/audit_orchestrator.py (ZCode domain)
from audit.parser import parse  # Cursor-owned

def run_audit(lh_json):
    images = parse(lh_json)
    # ... ZCode's orchestration logic
```

**Rule:** Import and use, don't modify.

### Pull Request (PR) Model

When an agent creates new logic:

1. Implement on a feature branch (`feat/<agent>-<ticket>` or `fix/<topic>`)
2. Open a PR with:
   - Implementation code
   - Expected input/output examples (fixtures)
   - Unit test specifications (ZCode writes the actual test files)
3. ZCode reviews, writes/updates tests, integrates
4. ZCode merges when tests pass

### Fixture Handoff

**Worker agent provides:**
```text
fixtures/
├── bad_hero_lcp.json
└── expected_output_bad_hero.json
```

**ZCode writes:**
```python
# tests/test_parser.py
def test_parser_bad_hero():
    with open("fixtures/bad_hero_lcp.json") as f:
        result = parse(json.load(f))
    with open("fixtures/expected_output_bad_hero.json") as f:
        expected = json.load(f)
    assert result == expected
```

---

## File Organization (Current State)

```text
shopify-image-audit/
├── src/
│   ├── audit/                    # Mixed ownership
│   │   ├── models.py             # ZCode-owned
│   │   ├── parser.py             # Cursor/Grok-owned
│   │   ├── ranker_heuristic.py   # Cursor/Grok-owned
│   │   ├── ranker_ml.py          # Cursor/Grok (Phase 3 placeholder)
│   │   ├── lighthouse_runner.py  # ZCode-owned (reserved for refactor)
│   │   └── report.py             # Windsurf/ChatGPT + ZCode
│   ├── core/                     # Cursor/Grok-owned
│   │   ├── image_extractor.py
│   │   └── performance_scorer.py
│   ├── engine/                   # ZCode-owned
│   │   ├── cli.py
│   │   └── audit_orchestrator.py
│   └── integrations/             # ZCode-owned
│       └── pagespeed_api.py
├── tests/                        # ZCode ONLY (single-writer)
├── schemas/                      # Windsurf/ChatGPT-owned
├── docs/                         # Windsurf/ChatGPT-owned
├── fixtures/                     # Shared (creator owns authored fixture content)
└── pyproject.toml                # ZCode-owned
```

---

## Quality Gates

### Before Merge to Main

**ZCode (coordinator) Checklist:**
- [ ] All tests pass (currently 143/143)
- [ ] Pydantic models validate against `schemas/audit_result.schema.json`
- [ ] CLI commands work end-to-end
- [ ] Code coverage maintained
- [ ] No regressions

**Cursor/Grok Checklist:**
- [ ] Fixtures provided for all code paths
- [ ] Expected outputs documented
- [ ] Algorithm performance benchmarked

**Windsurf/ChatGPT Checklist:**
- [ ] Schema updated if the data model changed
- [ ] Documentation reflects current behavior
- [ ] `QA_CHECKLIST.md` updated with new gates

---

## Communication Protocol

### Branch Naming
- `feat/zcode-<ticket>` / `fix/<topic>` — ZCode work
- `feat/cursor-<ticket>` — Cursor/Grok work
- `feat/windsurf-<ticket>` — Windsurf/ChatGPT work

### Commit Messages
```text
<DOMAIN>-<TICKET>: <description>

CU-003: Implement baseline manager
WS-004: Add customer report template
```

### When Domains Conflict
1. Raise an issue in the project discussion
2. Document the decision in this file
3. Update ownership if boundaries change

---

## Sprint 1 Post-Mortem (Historical)

The original 3×3 model assigned work to Claude/JetBrains, Cursor/Grok, and
Windsurf/ChatGPT. In practice Sprint 1 skewed heavily toward Claude/JetBrains
(82.2% of the codebase) because `src/audit/` was unassigned and Claude filled it
by necessity. As of Sprint 2, Claude/PyCharm has exited; ZCode absorbs its
domains. The historical authorship record is preserved below for traceability.

| Domain | Planned | Actual Sprint 1 | Note |
|--------|---------|-----------------|------|
| Claude/JetBrains | ~40% | 82.2% (1,982 lines) | Exited Sprint 2 → ZCode |
| Cursor/Grok | ~40% | 16.2% (302 lines) | Continues |
| Windsurf/ChatGPT | ~20% | 1.6% | Continues |

---

## Phase 2 (Sprint 2) Plan

**Goal:** Complete Phase 1 business validation and begin Phase 2 integrations.
See `docs/SPRINT_2_PLAN.md` for the full breakdown.

### Ownership rebalance
- ZCode (coordinator): engine, tests, models — maintenance + new CLI commands
- Cursor/Grok (+24% target): baseline manager, before/after workflow, live store support
- Windsurf/ChatGPT (+18% target): customer report templates, onboarding docs, multi-format exports

---

## Version History

| Version | Date       | Changes                                                                                       |
| ------- | ---------- | --------------------------------------------------------------------------------------------- |
| 1.0     | 2026-03-01 | Initial 3×3 model definition                                                                  |
| 1.1     | 2026-03-08 | Post Sprint 1: formalize `src/audit/` ownership, clarify ownership vs. authorship             |
| 1.2     | 2026-07-29 | Sprint 2: Claude/PyCharm exit; ZCode becomes coordinator + absorbs engine/tests/models domain |

---

## References

- See `archive/sprint1-analysis/CLAUDE_DOMAIN_REPORT.md` for detailed code analysis
- See `docs/SPRINT_1_COMPLETE.md` for Sprint 1 completion summary
- See `docs/SPRINT_2_PLAN.md` for the active sprint plan
