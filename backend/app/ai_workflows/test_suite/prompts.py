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
- suite_type: one of: positive | negative | boundary
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
   - authentication : login, register, tokens, sessions, SSO, 2FA, password reset
   - session_cleanup : logout, signout, session termination
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
STEP 2 — ORDER THE BUSINESS FLOWS BY EXECUTION DEPENDENCY

After classifying all TCs, determine the EXECUTION ORDER of flows.
This order is critical: it defines which test cases MUST run before others.

🔑 KEY PRINCIPLE — DATA & TOKEN DEPENDENCIES:
A test case CANNOT run unless its prerequisites are satisfied.
Examples of mandatory ordering:
  • Authentication BEFORE any authenticated flow — other TCs need the JWT token
  • User creation (CRUD) BEFORE reading/displaying that user (Dashboard)
  • Payment setup BEFORE checkout flow — payment method must exist first
  • Product creation BEFORE search — you cannot search what doesn't exist
  • API endpoints BEFORE automated tests — tests run against existing APIs

Ask yourself for each flow:
  "Does this flow PRODUCE data/tokens/state that OTHER flows CONSUME?"
  → If YES, it must execute FIRST.
  "Does this flow CONSUME data/tokens/state from another flow?"
  → If YES, that other flow must execute BEFORE this one.

Ordering rules:
  1. Flows with NO dependencies go first
  2. Flows that CREATE shared state (auth tokens, base records) go before flows that USE that state
  3. session_cleanup (logout) MUST always be the LAST flow — it destroys the auth token
  4. Core business transactions like (payment, booking, order) precede secondary features like (FAQ, help, notifications)
  5. Risk level is SECONDARY — a low-risk authentication test still runs before a high-risk payment test

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT:

```json
{{
  "tc_classifications": [
    {{
      "tc_code": "TC-001",
      "business_flow": "authentication",
      "risk_level": "critical",
      "reasoning": "Tests login — produces JWT token required by all other test cases"
    }},
    {{
      "tc_code": "TC-002",
      "business_flow": "crud",
      "risk_level": "high",
      "reasoning": "Creates user record — dashboard and search TCs depend on this data existing"
    }},
    {{
      "tc_code": "TC-003",
      "business_flow": "dashboard",
      "risk_level": "medium",
      "reasoning": "Reads user data — depends on TC-002 (CRUD) having created the user first"
    }},
    {{
      "tc_code": "TC-004",
      "business_flow": "api",
      "risk_level": "medium",
      "reasoning": "Tests API docs — documents endpoints created by CRUD flow"
    }}
  ],
  "flow_order": [
    {{
      "flow": "authentication",
      "rank": 1,
      "reason": "GATEWAY: Produces JWT tokens consumed by ALL other flows. Must run first.",
      "tc_count": 2,
      "risk_breakdown": {{"critical": 1, "high": 1}}
    }},
    {{
      "flow": "crud",
      "rank": 2,
      "reason": "Creates base data records consumed by Dashboard (display) and Search (query). Needs auth token from rank 1.",
      "tc_count": 3,
      "risk_breakdown": {{"critical": 1, "high": 1, "medium": 1}}
    }},
    {{
      "flow": "api",
      "rank": 3,
      "reason": "Documents CRUD endpoints — must run after endpoints exist. Needs auth token.",
      "tc_count": 1,
      "risk_breakdown": {{"medium": 1}}
    }},
    {{
      "flow": "dashboard",
      "rank": 4,
      "reason": "Displays data created by CRUD — depends on both auth token and CRUD records.",
      "tc_count": 2,
      "risk_breakdown": {{"high": 1, "medium": 1}}
    }},
    {{
      "flow": "search",
      "rank": 5,
      "reason": "Searches data created by CRUD — needs records to exist first.",
      "tc_count": 2,
      "risk_breakdown": {{"medium": 2}}
    }},
    {{
      "flow": "error_handling",
      "rank": 6,
      "reason": "Tests error scenarios for existing flows — runs after core flows are validated.",
      "tc_count": 2,
      "risk_breakdown": {{"high": 1, "medium": 1}}
    }},
    {{
      "flow": "monitoring",
      "rank": 7,
      "reason": "Monitors system health — meaningful only after core features operate.",
      "tc_count": 2,
      "risk_breakdown": {{"high": 1, "medium": 1}}
    }},
    {{
      "flow": "testing",
      "rank": 8,
      "reason": "Automated tests validate everything — runs last after all features confirmed working.",
      "tc_count": 1,
      "risk_breakdown": {{"low": 1}}
    }}
  ],
  "reasoning": "Auth (rank 1) is the gateway: JWT tokens are required by all other flows. CRUD (rank 2) creates base records that Dashboard, Search, and API depend on. API docs (rank 3) document CRUD endpoints. Dashboard (rank 4) and Search (rank 5) display/query CRUD data. Error handling (rank 6) tests edge cases of core flows. Monitoring (rank 7) tracks operational health. Automated tests (rank 8) validate everything end-to-end.",
  "project_context_summary": "Internal admin dashboard with authentication-gated features. All 8 user stories require JWT auth. Core data is created via CRUD, then displayed on Dashboard and queried via Search. API layer documents all endpoints."
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL RULES:

✅ EVERY test case MUST appear in tc_classifications

✅ EVERY detected flow MUST appear in flow_order

✅ The rank order MUST reflect actual data/token dependencies in THIS project

✅ Risk breakdown in flow_order MUST match tc_classifications

✅ tc_count in flow_order MUST match actual count

✅ Explain WHY each flow depends on the previous one (what data/token/state it needs)
"""