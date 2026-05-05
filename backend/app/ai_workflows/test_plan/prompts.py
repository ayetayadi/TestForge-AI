"""
LLM prompt for ISTQB §5.1.1 test plan generation.
"""

TEST_PLAN_PROMPT = """You are an ISTQB-certified test manager writing a test plan (section 5.1.1).

Generate a complete test plan draft for the project below, based on the risk analysis results.

PROJECT CONTEXT:
- Project name : {project_name}
- Project key  : {project_key}
- Scope type   : {scope_type}  (epic | sprint | release | manual)
- Scope refs   : {scope_refs}
- Environment  : {environment_hint}

USER STORIES IN SCOPE ({story_count} stories):
{stories_summary}

RISK ANALYSIS RESULTS:
- Critical (score ≥ 4.0): {count_critical} stories
- High    (2.5 – 3.9)  : {count_high} stories
- Medium  (1.0 – 2.4)  : {count_medium} stories
- Low   (< 1.0)      : {count_low} stories

TOP RISKS IDENTIFIED (with mitigation strategies):
{top_risks}
# ↑ FORMAT: Each risk includes description, test_depth, mitigation
# Example:
#   • [20.0] Payment fails when applying promo code during peak hours
#     Test depth: comprehensive
#     Mitigation: Test checkout with 10 promo codes + load test 1000 concurrent users


═══════════════════════════════════════
INSTRUCTIONS FOR RISK-BASED TEST PLAN:
═══════════════════════════════════════

1. **TITLE** — short, professional (max 100 characters). Include project name and scope.
   TITLE RULES:
   • If scope_type is "sprint" and multiple sprints: "Test Plan — {project_name} — {sprint_count} Sprints ({scope_refs})"
   • If scope_type is "epic" and multiple epics: "Test Plan — {project_name} — {epic_count} Epics ({scope_refs})"
   • If scope_type is "sprint" and single sprint: "Test Plan — {project_name} — {scope_refs}"
   • If scope_type is "epic" and single epic: "Test Plan — {project_name} — {scope_refs}"
   • Otherwise: "Test Plan — {project_name} — {scope_type}"
   • NEVER use generic titles like "USM - Sprint 1 Testing" (confusing and incorrect)

2. **DESCRIPTION** — 2-3 sentences summarizing:
   - What this test plan covers (scope, features, risk areas)

3. **OBJECTIVE** — 2-4 measurable testing objectives. Prioritize based on risk:
   - Verify behavior of critical/high-risk user stories
   - Validate that risk mitigation strategies are effective
   - Ensure no regression on previously stable features
   - Confirm acceptance criteria are met for all stories in scope

4. **IN SCOPE** — Bullet list of what IS covered:
   - List specific features, modules, or user stories
   - Mention high-risk areas explicitly

5. **OUT OF SCOPE** — Bullet list of what is NOT covered:
   - Be explicit about exclusions (performance testing, third-party APIs, security scans, etc.)
   - Justify why certain areas are excluded (timeline, environment, risk level)

6. **ENVIRONMENT** — Choose from: dev, staging, prod, uat
   Pick the MOST APPROPRIATE for this scope:
   - "dev" : early development, not for formal testing
   - "staging" : pre-production, ideal for most test plans
   - "prod" : production-like environment, for smoke/sanity tests only
   - "uat" : user acceptance testing environment

9. **ENTRY CRITERIA** — 3-4 conditions that MUST be true BEFORE testing starts:
   - Build deployed to target environment
   - Smoke tests passed
   - Test data prepared and validated
   - All critical/high risks reviewed and accepted by QA Lead

10. **EXIT CRITERIA** — 3-4 MEASURABLE conditions that mark testing as DONE:
    - 100% of critical test cases executed
    - 95% of high test cases executed
    - 0 open critical defects
    - All risk mitigations verified and signed off
    - Test summary report delivered to stakeholders

11. **APPROACH** — Describe the testing strategy (3-5 sentences):
    - Risk-based prioritization: test critical/high risks FIRST
    - For EACH top risk, incorporate its MITIGATION strategy into the test approach
    - Mention automation intent (which tests to automate first)
    - Describe the test execution order based on risk score and test depth

12. **ASSUMPTIONS** — 2-3 hypotheses the team is relying on:
    - Environment stability and availability
    - Test data accurately reflects production scenarios
    - Developers available for critical defect fixes during test execution

13. **CONSTRAINTS** — 2-3 real constraints:
    - Resource availability (QA engineers, devices, licenses)
    - Tool access limitations (test management, automation frameworks)

14. **REASONING** — Brief explanation of your main choices (2-3 sentences):
    - How the approach addresses the identified risks and mitigations

15. **STAKEHOLDERS** — Roles and responsibilities:
    - QA Engineer: executes tests, reports defects, automates test cases
    - Developer: fixes critical defects, supports test environment setup
    - Product Owner: reviews test scope, accepts/rejects Test Plan, signs off on exit criteria
    - Tech Lead: ensures environment readiness, approves technical approach

16. **COMMUNICATION** — How the team will communicate about testing:
    - Daily standup: progress updates, blockers, defect triage
    - Progress reports: daily test execution metrics (passed/failed/blocked)
    - Defect reports: critical defects flagged immediately via Slack/Teams
    - Closure report: final test summary with metrics, lessons learned

═══════════════════════════════════════
GENERATE THE TEST PLAN NOW.
═══════════════════════════════════════
"""