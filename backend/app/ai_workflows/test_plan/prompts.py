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

TOP RISKS IDENTIFIED:
{top_risks}

ESTIMATED DURATION: {duration_optimistic}–{duration_pessimistic} working days (PERT realistic: {duration_realistic} days)

RECOMMENDED TEST TYPES: {recommended_types}
RECOMMENDED TEST LEVELS: {recommended_levels}

RULES:
- title: short, professional (max 100 characters). Include project name and scope.
  TITLE RULES:
  • If scope_type is "sprint" and multiple sprints: use "Test Plan — {project_name} — {sprint_count} Sprints ({scope_refs})"
  • If scope_type is "epic" and multiple epics: use "Test Plan — {project_name} — {epic_count} Epics ({scope_refs})"
  • If scope_type is "sprint" and single sprint: use "Test Plan — {project_name} — {scope_refs}"
  • If scope_type is "epic" and single epic: use "Test Plan — {project_name} — {scope_refs}"
  • Otherwise: use "Test Plan — {project_name} — {scope_type}"
  • NEVER use: "USM - Sprint 1 Testing" (this is confusing and incorrect)
- description: 2-3 sentences summarizing what this test plan covers and why
- objective: 2-4 measurable testing objectives (what we want to verify)
- in_scope: bullet list of what IS covered (features, modules, risk areas)
- out_of_scope: bullet list of what is NOT covered (performance, third-party APIs, etc.) — be explicit
- test_types: MUST be a JSON array. Choose from: ["functional", "regression", "smoke", "security", "performance", "e2e", "api"]. Example: ["functional", "security"]
- test_levels: MUST be a JSON array. Choose from: ["component", "integration", "system", "acceptance", "e2e"]. Example: ["system", "acceptance"]
- environment: choose from: dev, staging, prod, uat — pick the most appropriate for this scope
- entry_criteria: 3-4 conditions that must be true BEFORE testing starts (build deployed, smoke passed, test data ready)
- exit_criteria: 3-4 measurable conditions that mark testing as DONE (e.g. 100% critical TCs executed, 0 open critical defects)
- approach: describe the testing strategy (risk-based prioritization, test types mix, automation intent)
- assumptions: 2-3 hypotheses the team is relying on (stable environment, test data available, devs available for fixes)
- constraints: 2-3 real constraints (timeline, resource availability, tool access)
- reasoning: brief explanation of your main choices (why these test types, why this scope)
- stakeholders: roles and responsibilities of key stakeholders (QA Engineer, Developer, PO, Tech Lead)
- communication: how will the team communicate about testing progress and issues (daily standup, progress reports, defect reports, closure report)
Generate the test plan now.
"""  
