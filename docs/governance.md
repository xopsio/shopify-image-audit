# Governance & Domain Ownership

**Last updated:** 2026-03-08 (Post Sprint 1 Analysis)  
**Project:** shopify-image-audit  
**Model:** 3×3 Multi-Agent Development

---

## Overview

This project uses a multi-agent development model where three AI assistants work in parallel, each owning specific domains. This document defines ownership boundaries, responsibilities, and integration protocols.

---

## Domain Ownership

### JetBrains/Claude (Primary: Backend Integration & Testing)

**Assigned Domains:**
- `src/engine/` - Orchestration, CLI, pipeline integration
- `tests/` - All test files, test harness, fixtures
- `pyproject.toml` - Packaging, dependencies, build configuration

**Sprint 1 Expansion (Formally Recognized):**
- `src/audit/models.py` - Pydantic data models (unassigned → implemented by necessity)
- `src/audit/report.py` - HTML report generation (unassigned → implemented by necessity)

**Current Ownership (Post Sprint 1):**
- All of `src/audit/` directory (effective governance v1.1)
- This includes files originally authored by other domains

**Responsibilities:**
- Orchestrator pipeline implementation
- CLI interface (run, extract, score, report commands)
- Data model validation (Pydantic v2)
- Test suite ownership (single-writer for determinism)
- Integration of core components from other domains
- Packaging and deployment configuration

**Actual Sprint 1 Output:** 1,982 lines (82.2% of codebase)

---

### Cursor/Grok (Primary: Core Algorithms)

**Assigned Domains:**
- `src/core/` - Core algorithms, extractors, scorers (Phase 2)

**Sprint 1 Authorship:**
- `src/audit/parser.py` - Lighthouse JSON parser (183 lines)
- `src/audit/ranker_heuristic.py` - Heuristic scoring algorithm (119 lines)

**Current Ownership:**
- No files under `src/audit/` are Cursor-owned after governance v1.1
- Ownership returns to Cursor when parser/ranker are migrated to `src/core/`

**Note:** Originally planned for `src/core/`, implemented in `src/audit/` during Sprint 1. Folder naming diverged from the initial plan.

**Responsibilities:**
- Image extraction from Lighthouse JSON
- Performance scoring algorithms (heuristic v1, ML-based planned)
- Feature engineering for scoring
- Algorithm optimization

**Actual Sprint 1 Authorship:** 302 lines (via parser + ranker in `src/audit/`)

---

### Windsurf/ChatGPT (Primary: Specification & Documentation)

**Assigned Domains:**
- `schemas/` - JSON schemas, data contracts
- `docs/` - Specifications, runbooks, documentation
- `QA_CHECKLIST.md` - Quality gates, acceptance criteria

**Responsibilities:**
- Schema definitions (`audit_result.schema.json`)
- CLI specifications
- Measurement protocols
- Quality assurance criteria
- Documentation maintenance

**Actual Sprint 1 Output:** Complete (schemas, docs, QA checklist)

---

## Single-Writer Rule

**Critical Principle:** Each folder/file has exactly ONE domain as the "truth owner."

### Why This Matters
- **Determinism:** Tests must be reproducible (JetBrains-only)
- **Conflict Avoidance:** No merge conflicts within a domain
- **Clear Accountability:** Each domain owns its outputs

### How It Works
1. Domain A implements a feature in its folder
2. Domain A creates a PR with the implementation
3. Domain B integrates via import/API (no direct editing)
4. If Domain B needs changes → PR to Domain A, not direct edit

---

## Sprint 1 Post-Mortem Analysis

### Planned vs. Actual Domain Distribution

| Domain | Planned | Actual Sprint 1 | Variance |
|--------|---------|-----------------|----------|
| Claude/JetBrains | ~40% | 82.2% (1,982 lines) | +42.2% |
| Cursor/Grok | ~40% | 16.2% (302 lines via `src/audit/`) | -23.8% |
| Windsurf/ChatGPT | ~20% | 1.6% | -18.4% |

### Root Cause: `src/audit/` Was Unassigned

The `src/audit/` folder (792 total lines) was not explicitly assigned in the original 3×3 model:
- `models.py` (98 lines) - Claude authored (needed for pipeline)
- `report.py` (392 lines) - Claude authored (needed for MVP)
- `parser.py` (183 lines) - Cursor authored (should be in `src/core/`)
- `ranker_heuristic.py` (119 lines) - Cursor authored (should be in `src/core/`)

### Decision: Accept Reality, Formalize Ownership

**Effective immediately:**
- `src/audit/` → **JetBrains/Claude** (official current owner)
- Future work will rebalance toward the 40-40-20 target
- See `SPRINT_1_RETROSPECTIVE.md` for lessons learned

### Important Clarification: Ownership vs. Authorship

**Ownership and authorship are not the same thing:**

- **Ownership** = who has the right to modify and maintain the file going forward
- **Authorship** = who originally implemented the file in Sprint 1

**For Sprint 1 retrospective purposes:**
- `parser.py` and `ranker_heuristic.py` were authored by Cursor/Grok
- `models.py` and `report.py` were authored by JetBrains/Claude

**For current governance purposes:**
- `src/audit/` is owned by JetBrains/Claude until parser/ranker are migrated to `src/core/`
- This maintains the single-writer rule at the folder level

---

## Integration Protocol

### Cross-Domain Dependencies

**Example: Claude integrates Cursor-authored parser**
```python
# src/engine/audit_orchestrator.py (Claude domain)
from audit.parser import parse  # Cursor-authored, Claude-owned

def run_audit(lh_json):
    images = parse(lh_json)
    # ... Claude's orchestration logic
```

**Rule:** Import and use, don't modify.

### Pull Request (PR) Model

When Cursor/Grok creates parser/ranker logic:

1. Cursor implements in a separate branch (for example `dev/cursor-parser`)
2. Cursor creates a PR with:

   * Implementation code
   * Expected input/output examples (fixtures)
   * Unit test specifications (not actual test files)
3. JetBrains reviews, writes tests, integrates
4. JetBrains merges when tests pass

### Fixture Handoff

**Cursor/Grok provides:**

```text
fixtures/
├── bad_hero_lcp.json
└── expected_output_bad_hero.json
```

**JetBrains/Claude writes:**

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
│   ├── audit/                    # Current owner: JetBrains/Claude
│   │                             # Historical authorship includes Cursor work (parser/ranker)
│   │   ├── models.py             # Claude-authored, Claude-owned
│   │   ├── parser.py             # Cursor-authored, Claude-owned
│   │   ├── ranker_heuristic.py   # Cursor-authored, Claude-owned
│   │   └── report.py             # Claude-authored, Claude-owned
│   └── engine/                   # Claude-owned (orchestration)
│       ├── cli.py
│       └── audit_orchestrator.py
├── tests/                        # Claude ONLY (single-writer)
├── schemas/                      # Windsurf-owned (data contracts)
├── docs/                         # Windsurf-owned (specs, runbooks)
├── fixtures/                     # Shared (creator owns authored fixture content)
└── pyproject.toml                # Claude-owned (packaging)
```

---

## Quality Gates

### Before Merge to Main

**JetBrains/Claude Checklist:**

* [ ] All tests pass (103/103 currently)
* [ ] Pydantic models validate against schema
* [ ] CLI commands work end-to-end
* [ ] Security fixes applied (no Qodo blockers)
* [ ] Code coverage maintained

**Cursor/Grok Checklist:**

* [ ] Fixtures provided for all code paths
* [ ] Expected outputs documented
* [ ] Algorithm performance benchmarked

**Windsurf/ChatGPT Checklist:**

* [ ] Schema updated if the data model changed
* [ ] Documentation reflects current behavior
* [ ] `QA_CHECKLIST.md` updated with new gates

---

## Communication Protocol

### Branch Naming

* `dev/jetbrains-<ticket>` - Claude work
* `dev/cursor-<ticket>` - Grok work
* `dev/windsurf-<ticket>` - ChatGPT work

### Commit Messages

```text
<DOMAIN>-<TICKET>: <description>

JB-001: Add HTML report generation
CU-002: Implement ML-based ranker
WS-003: Update CLI specification
```

### When Domains Conflict

1. Raise an issue in project discussion
2. Document the decision in this file
3. Update ownership if boundaries change

---

## Phase 2 Planning

### Goal: Rebalance toward 40-40-20

**Cursor/Grok expansion (+24% target):**

* Move parser/ranker to `src/core/` (restore direct ownership)
* Add ML-based scoring (~400-600 lines)
* Implement image optimization recommendations

**Windsurf/ChatGPT expansion (+18% target):**

* Report theming system
* Multi-format exports (PDF, CSV)
* Enhanced documentation

**Claude/JetBrains (maintenance mode):**

* Bug fixes only
* Integration testing
* Performance optimization

---

## Version History

| Version | Date       | Changes                                                                                                     |
| ------- | ---------- | ----------------------------------------------------------------------------------------------------------- |
| 1.0     | 2026-03-01 | Initial 3×3 model definition                                                                                |
| 1.1     | 2026-03-08 | Post Sprint 1 update: formalize `src/audit/` ownership, clarify ownership vs. authorship, document variance |

---

## References

* See `archive/sprint1-analysis/CLAUDE_DOMAIN_REPORT.md` for detailed code analysis
