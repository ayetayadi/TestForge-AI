"""
LLM prompts for test suite naming and business flow ordering.
"""

TEST_SUITE_NAMING_PROMPT = """You are an ISTQB-certified test manager organizing test cases into test suites.

Generate a professional title and description for each test suite group below.

PROJECT: {project_name}
GROUPING STRATEGY: {strategy}

SUITE GROUPS TO NAME:
{suite_groups}

RULES:
- title: short, professional, max 80 chars
  Examples: "Critical Authentication Tests", "Boundary Value Tests — User Registration"
- description: 1-2 sentences explaining what this suite covers and its purpose
- suite_type: one of: feature | epic | sprint | smoke | regression | negative | security | performance | e2e
- priority: one of: critical | high | medium | low (based on the risk level of included tests)

Generate one entry per group in the list above.
"""

BUSINESS_FLOW_ORDERING_PROMPT = """You are a QA architect with ISTQB Advanced Test Manager certification.

Your task: Analyze ALL test cases below and determine:
  1. The BUSINESS FLOW of EACH test case (what does it REALLY test?)
  2. The RISK LEVEL of EACH test case (how critical is it?)
  3. The EXECUTION ORDER of business flows for THIS specific project

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROJECT CONTEXT:
{project_name}

{user_stories_summary}

TEST CASES TO ANALYZE:
{test_cases_summary}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ CRITICAL: You MUST classify EVERY test case listed above. No exceptions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — CLASSIFY EACH TEST CASE

For EVERY test case, determine:

A) BUSINESS FLOW — What does this TC ACTUALLY test?
   Look BEYOND the title. Consider:
   - What is the PRIMARY action being tested?
   - What user story does it belong to?
   - What is the END GOAL of this test?
   
   Available flows:
   - authentication : login, logout, register, tokens, sessions, SSO, 2FA, password reset
   - authorization : permissions, roles, access control, admin vs user
   - crud : create, read, update, delete operations on data
   - dashboard : overview, home, landing, visualization, display, view
   - search : search, filter, sort, query, find, browse, pagination
   - api : endpoints, documentation, swagger, REST, integration, curl
   - error_handling : validation, error messages, HTTP errors, edge cases
   - reporting : report, export, audit, analytics, metrics, statistics, logs
   - monitoring : health checks, alerts, tracking, activity, performance
   - notifications : email, SMS, push, reminders, broadcasts
   - settings : config, preferences, profile, account management
   - testing : automated tests, CI/CD, coverage, jest, playwright, pipeline
   - other : anything not matching above

B) RISK LEVEL — How critical is this TC?
   Consider:
   - What happens if this test FAILS in production?
   - Does it block other features?
   - Is it a security concern?
   - Is it a core business function?
   
   Risk levels:
   - critical : Failure = system down, data loss, security breach, business stops
   - high : Failure = major feature broken, significant user impact
   - medium : Failure = feature partially broken, workaround exists
   - low : Failure = minor issue, cosmetic, edge case

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — ORDER THE BUSINESS FLOWS

After classifying all TCs, determine the execution order of flows:
  1. What MUST execute FIRST? (Gateway/entry point)
  2. What DEPENDS on other flows?
  3. What is the NATURAL user journey?

Rules:
- A flow with NO dependencies executes first
- A flow that CREATES data executes before flows that READ it
- Authentication usually executes first IF the system requires login
- BUT if it's a public site, Dashboard/Search may come first
- Risk level is SECONDARY to business flow

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT:

```json
{{
  "tc_classifications": [
    {{
      "tc_code": "TC-001",
      "business_flow": "authentication",
      "risk_level": "critical",
      "reasoning": "Tests login — if login fails, entire system is inaccessible"
    }},
    {{
      "tc_code": "TC-002",
      "business_flow": "crud",
      "risk_level": "high",
      "reasoning": "Tests user creation — core admin function, but doesn't block login"
    }},
    {{
      "tc_code": "TC-003",
      "business_flow": "dashboard",
      "risk_level": "medium",
      "reasoning": "Tests dashboard display — depends on CRUD data existing"
    }},
    {{
      "tc_code": "TC-004",
      "business_flow": "api",
      "risk_level": "medium",
      "reasoning": "Tests API documentation — documents existing endpoints"
    }}
  ],
  "flow_order": [
    {{
      "flow": "authentication",
      "rank": 1,
      "reason": "Gateway to entire system — all 8 user stories require JWT tokens",
      "tc_count": 2,
      "risk_breakdown": {{"critical": 1, "high": 1}}
    }},
    {{
      "flow": "crud",
      "rank": 2,
      "reason": "Creates data that Dashboard, API, and Reports depend on",
      "tc_count": 3,
      "risk_breakdown": {{"critical": 1, "high": 1, "medium": 1}}
    }},
    {{
      "flow": "api",
      "rank": 3,
      "reason": "Documents CRUD endpoints — must come after endpoints exist",
      "tc_count": 1,
      "risk_breakdown": {{"medium": 1}}
    }},
    {{
      "flow": "dashboard",
      "rank": 4,
      "reason": "Displays CRUD data visually — depends on data existing",
      "tc_count": 2,
      "risk_breakdown": {{"high": 1, "medium": 1}}
    }},
    {{
      "flow": "error_handling",
      "rank": 5,
      "reason": "Tests error scenarios alongside core flows",
      "tc_count": 2,
      "risk_breakdown": {{"high": 1, "medium": 1}}
    }},
    {{
      "flow": "monitoring",
      "rank": 6,
      "reason": "Monitors system after all features are operational",
      "tc_count": 2,
      "risk_breakdown": {{"high": 1, "medium": 1}}
    }},
    {{
      "flow": "testing",
      "rank": 7,
      "reason": "Automated tests validate everything — runs last",
      "tc_count": 1,
      "risk_breakdown": {{"low": 1}}
    }}
  ],
  "reasoning": "Auth is the gateway (rank 1) because US-1 (JWT Auth), US-3 (Login), and US-6 (Auth Middleware) all require valid tokens. CRUD (rank 2) creates the data that Dashboard (rank 4) displays and API (rank 3) documents. Error handling (rank 5) validates edge cases alongside core flows. Monitoring (rank 6) tracks system health. Automated tests (rank 7) run last to validate everything.",
  "project_context_summary": "This is an internal admin dashboard with 8 user stories spanning authentication, CRUD operations, API documentation, monitoring, error handling, and automated testing. All features require authentication."
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL RULES:

✅ EVERY test case MUST appear in tc_classifications

✅ EVERY detected flow MUST appear in flow_order

✅ Risk breakdown in flow_order MUST match tc_classifications

✅ tc_count in flow_order MUST match actual count

✅ Order must reflect THIS project's actual dependencies

✅ Explain your reasoning for each classification
"""