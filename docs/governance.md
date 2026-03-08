# Governance & Domain Division

Projektin kehitys on jaettu selkeisiin domain-alueisiin, joilla on omat omistajat ja rajat. Tämä jako noudattaa single-writer-periaatetta ja estää ristiriidat spec- ja implementation-tasojen välillä.

## Domain-jako

- **Spec / Contracts**  
  Omistaja: Windsurf / Spec-domain  
  Branch: `dev/windsurf-spec-clean`  
  Sisältö:  
  - `docs/` (CLI-spec, runbook, governance)  
  - `schemas/` (audit_result.schema.json ym.)  
  - `QA_CHECKLIST.md` (QA-gates, single source of truth -periaate)  
  Tarkoitus: Määrittelee sopimukset, skeemat ja laadunvarmistussäännöt. Ei sisällä toteutuskoodia.  
  Muutokset: Vain spec-domainin kautta, ei retroaktiivisia päivityksiä toteutuksen perusteella.

- **Core Audit**  
  Omistaja: Grok / Cursor-domain  
  Polku: `src/audit/`  
  Sisältö:  
  - parser.py  
  - ranker_heuristic.py  
  - ranker_ml.py (placeholder tai lukittu Sprint 1:ssä)  
  - lighthouse_runner.py (lukittu Sprint 1:ssä)  
  Tarkoitus: Analyysin ydin – JSON/Lighthouse-datan parsiminen, heuristinen/ML-pisteytys ja priorisointi.

- **Engine / CLI / Tests**  
  Omistaja: JetBrains / Claude-domain (JB-domain)  
  Polku: `src/engine/`, `tests/`  
  Sisältö:  
  - audit_orchestrator.py  
  - cli.py  
  - models.py (jos siirretty tänne)  
  - Testit (test_models.py, test_pipeline.py ym.)  
  Tarkoitus: Putken orkestrointi, CLI-käyttöliittymä, validointi ja automaattiset testit.  
  Historia: Mergeattu `dev/jetbrains-engine`-branchista (commit fa72ee3).

## Periaatteet

- Jokainen domain on single-writer: vain kyseisen domainin omistaja muokkaa omia polkujaan.
- Spec-domain toimii staattisena sopimuksena – se ei päivity automaattisesti toteutuksen perusteella.
- Muutokset toteutukseen eivät retroaktiivisesti muuta spec-dokumentaatiota ilman eksplisiittistä päätöstä ja review'ta.
- QA_CHECKLIST.md määrittelee DoD (Definition of Done) ja gates Sprint 1:lle.

Tämä jako on dokumentoitu päätöksenä [päivämäärä: 2026-03-07] ja sitä noudatetaan jatkokehityksessä.