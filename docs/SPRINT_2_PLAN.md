# Sprint 2 Plan

**Duration:** 3-4 weeks
**Status:** PLANNING
**Phase:** Vaihe 1 completion + Vaihe 2 start (per PDF roadmap)

---

## 1. Sprint 2 Goal

**Complete Phase 1 business validation and begin Phase 2 technical integrations.**

### Primary Objectives:
- Deliver before/after measurement workflow
- Integrate PageSpeed Insights API for automated LCP measurement
- Create customer-ready documentation and reporting templates
- Validate business model with first customer preparation

### Success Criteria:
- ✅ Automated before/after measurement works end-to-end
- ✅ PageSpeed API returns live LCP metrics
- ✅ Customer report template generates professional output
- ✅ First customer onboarding workflow documented

---

## 2. Business Deliverables

### BD-1: Before/After Measurement Workflow
**Owner:** Cursor/Grok (CU-003)
- Capture baseline metrics (LCP, image sizes, formats)
- Apply optimization recommendations
- Re-measure with PageSpeed API
- Generate comparison report

**Business Value:** Proves ROI to customers (e.g., "LCP 4.2s → 1.8s")

### BD-2: Customer Report Template
**Owner:** Windsurf/ChatGPT (WS-003)
- Professional audit report structure
- Before/after visualization
- ROI calculation (conversion impact estimate)
- Actionable recommendations prioritized by impact

**Business Value:** 99-199€ deliverable quality

### BD-3: First Customer Onboarding Workflow
**Owner:** Windsurf/ChatGPT (WS-003)
- Onboarding checklist
- Required Shopify store access
- Audit execution steps
- Delivery process documentation

**Business Value:** Enables first paid customer (Phase 1 milestone)

---

## 3. Technical Deliverables

### TD-1: PageSpeed Insights API Integration
**Owner:** JetBrains/Claude (JB-002)
- API client implementation (`src/integrations/pagespeed_api.py`)
- Fetch live LCP, CLS, INP metrics for Shopify store
- Rate limiting and error handling
- Cache results for re-runs

**Tech Stack:** Python, requests library, Google PSI API v5

### TD-2: Live Shopify Store Testing Support
**Owner:** Cursor/Grok (CU-003)
- Accept live store URL as input (not just Lighthouse JSON)
- Trigger PageSpeed API measurement
- Parse real-world performance data
- Support mobile/desktop variants

**Tech Stack:** Python, PageSpeed API, Lighthouse JSON parser

### TD-3: Before/After Comparison Engine
**Owner:** Cursor/Grok (CU-003)
- Store baseline audit result
- Re-run audit after optimization
- Calculate deltas (LCP improvement, file size reduction)
- Generate comparison JSON

**Tech Stack:** Python, JSON diff, metrics calculation

### TD-4: Enhanced HTML Report with Before/After
**Owner:** JetBrains/Claude (JB-002)
- Update `src/audit/report.py` template
- Add before/after comparison section
- Visualize LCP improvement (chart or table)
- Include ROI estimate based on conversion impact

**Tech Stack:** Python, Jinja2 (if templating), HTML/CSS

---

## 4. Ticket Breakdown

### JB-002: PageSpeed API Integration + Enhanced Reporting
**Owner:** JetBrains/Claude
**Domain:** `src/integrations/`, `src/audit/report.py` 
**Estimated:** 2-3 days

**Tasks:**
1. Create `src/integrations/pagespeed_api.py` 
   - API client with rate limiting
   - Fetch LCP, CLS, INP for given URL
   - Return structured metrics
2. Add CLI command: `audit measure <url>` 
   - Calls PageSpeed API
   - Outputs metrics JSON
3. Update `generate_html_report()` in `src/audit/report.py` 
   - Add before/after comparison section
   - Display LCP delta, file size reduction
   - Calculate estimated conversion impact (simple formula)
4. Write tests for API client
   - Mock API responses
   - Test error handling (rate limits, invalid URLs)
5. Update project dependencies and packaging
   - Add `requests` to `[project.dependencies]` in `pyproject.toml`
   - Add `responses` (or equivalent mock library) to `[project.optional-dependencies.dev]`
   - Verify `pip install -e .[dev]` succeeds with new dependencies

**Dependencies:** None (new integration)

**Acceptance Criteria:**
- ✅ CLI command `audit measure <url>` returns live LCP
- ✅ HTML report includes before/after comparison when data available
- ✅ Tests pass (API client + report generation)
- ✅ `pyproject.toml` updated with new dependencies (`requests`, test mocks)

---

### CU-003: Before/After Workflow + Live Store Support
**Owner:** Cursor/Grok
**Domain:** `src/core/`, `src/audit/` 
**Estimated:** 2-3 days

**Tasks:**
1. Create `src/core/baseline_manager.py` 
   - Save baseline audit result to JSON
   - Load baseline for comparison
   - Calculate deltas (LCP, image sizes, scores)
2. Update `src/audit/parser.py` to accept live URLs
   - If input is URL, call PageSpeed API (via JB-002 integration)
   - Parse Lighthouse JSON from API response
   - Fallback to local JSON file if provided
3. Add CLI workflow: `baseline` and `compare` commands
   - `audit baseline <url> --save baseline.json` 
   - `audit compare baseline.json <url> --output comparison.html` 
4. Test with real Shopify demo store
   - Run baseline measurement
   - Apply manual optimization (e.g., compress hero image)
   - Re-run and verify delta calculation

**Dependencies:** JB-002 (PageSpeed API client)

**Acceptance Criteria:**
- ✅ Baseline workflow saves/loads audit results
- ✅ Compare generates delta report (LCP before/after)
- ✅ Live URL input works end-to-end
- ✅ Demo store test case documented

---

### WS-003: Customer Documentation + Report Templates
**Owner:** Windsurf/ChatGPT
**Domain:** `docs/`, report templates
**Estimated:** 1-2 days

**Tasks:**
1. Create `docs/CUSTOMER_REPORT_TEMPLATE.md` 
   - Executive summary structure
   - Before/after metrics section
   - Prioritized recommendations
   - ROI estimate methodology
2. Create `docs/CUSTOMER_ONBOARDING.md` 
   - Pre-audit checklist (Shopify access, baseline URL)
   - Audit execution steps
   - Delivery format (HTML report + PDF export optional)
   - Follow-up process
3. Update `docs/SPRINT_2_PLAN.md` (this document)
   - Finalize ticket breakdown
   - Add acceptance criteria
4. Generate example customer report
   - Use demo store data
   - Show realistic before/after (e.g., LCP 4.2s → 1.8s)
   - Professional formatting

**Dependencies:** None (documentation only)

**Acceptance Criteria:**
- ✅ Customer report template is ready for first client
- ✅ Onboarding workflow documented
- ✅ Example report generated from demo store

---

## 5. Acceptance Criteria (Sprint-Level)

### Business Success:
- [ ] Before/after workflow proven with demo store
- [ ] Customer report template approved (internal review)
- [ ] First customer onboarding process documented
- [ ] ROI calculation methodology defined

### Technical Success:
- [ ] PageSpeed API integration works (live LCP measurement)
- [ ] Before/after comparison generates accurate deltas
- [ ] HTML report includes before/after section
- [ ] CLI commands: `measure`, `baseline`, `compare` functional
- [ ] All new code has tests (>80% coverage for new modules)

### Quality Gates:
- [ ] No regressions (103/103 tests still pass)
- [ ] Demo end-to-end: baseline → optimize → compare → report
- [ ] Documentation updated (README, API docs if added)

---

## 6. Out of Scope (Sprint 2)

### Explicitly NOT included:
- ❌ ML-based image scoring (Phase 3)
- ❌ GPU acceleration (Phase 3)
- ❌ C# extension layer (future sprint)
- ❌ .NET/C# reporting backend (future sprint)
- ❌ Shopify App development (Phase 2 later)
- ❌ Automated image optimization (future feature)
- ❌ PDF export (optional, can be added later)
- ❌ Multi-store batch processing (future feature)
- ❌ API authentication/user management (future)

### Deferred to Sprint 3+:
- Footer source filename fix (cosmetic, Qodo finding)
- Demo fallback consistency (robustness improvement)
- Advanced reporting (charts, graphs beyond basic table)

---

## 7. Timeline

**Week 1:**
- JB-002: PageSpeed API client + CLI measure command
- CU-003: Baseline manager + parser URL support

**Week 2:**
- JB-002: Enhanced HTML report with before/after
- CU-003: Compare workflow + demo store testing
- WS-003: Customer documentation templates

**Week 3:**
- Integration testing (full before/after workflow)
- Documentation finalization
- Example customer report generation

**Week 4 (buffer):**
- Bug fixes
- Quality assurance
- Sprint 2 retrospective

---

## 8. Dependencies

**External:**
- Google PageSpeed Insights API (free tier, no auth required for basic use)
- Live Shopify demo store (for testing)

**Internal:**
- Sprint 1 baseline (CLI, parser, scorer, HTML report)
- Current main branch (639a851)

---

## 9. Risks & Mitigations

**Risk 1: PageSpeed API rate limits**
- Mitigation: Implement caching, local Lighthouse fallback for dev

**Risk 2: Live store access for testing**
- Mitigation: Use public demo stores or create test Shopify account

**Risk 3: Scope creep (ML/C# requests)**
- Mitigation: Strict adherence to "Out of Scope" section

---

## 10. Success Metrics

**Business KPIs:**
- First customer onboarding workflow ready
- Customer report template approved
- Before/after proof (demo store case)

**Technical KPIs:**
- PageSpeed API integration functional
- Before/after delta calculation accurate
- Zero test regressions
- Enhanced HTML report deployed

---

**Sprint 2 Start:** TBD
**Sprint 2 End:** TBD
**Retrospective:** After Sprint 2 completion

---

**Next Steps:**
1. Review and approve this plan
2. Create GitHub issues/tickets for JB-002, CU-003, WS-003
3. Assign to respective agents/domains
4. Begin Sprint 2 development
