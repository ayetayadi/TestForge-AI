TEST_CASE_GENERATION_PROMPT = """You are an ISTQB-certified test analyst.

Generate structured test cases for the user story below. Each test case must include
ALL required fields: preconditions, postconditions, steps, test data, expected results,
and a Gherkin BDD scenario block.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER STORY:
{story}

ACCEPTANCE CRITERIA:
{acceptance_criteria}

RISK LEVEL: {risk_level} (risk score: {risk_score})
RISK DESCRIPTION: {risk_description}
MITIGATION: {risk_mitigation}

ACCEPTED RISK IDs LINKED TO THIS USER STORY:
{risk_ids_list}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TEST TYPE REQUESTED: {scenario_type}
  • positive   → happy path, valid input, expected successful outcome
  • negative   → invalid input, error path, rejected operations
  • boundary   → limit values (max/min length, 0, -1, empty, null, special chars)

Generate exactly {count} test case(s) of type "{scenario_type}".
Deduce concrete scenarios from the acceptance criteria above — even for negative and
boundary types, derive them from what the positive ACs imply (invalid/limit counterparts).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIELD DEFINITIONS — fill EVERY field for EVERY test case:

title
  Short imperative sentence (max 100 chars).
  Examples: "Login with valid credentials", "Reject blank password field"

test_type
  Must be exactly: {scenario_type}

priority
  One of: critical | high | medium | low
  (critical = blocks the core user flow; use sparingly)

preconditions
  List of strings — system state required BEFORE the test starts.
  Examples:
    - "User account exists with email test@example.com"
    - "User is NOT logged in"
    - "Database contains at least 1 active product"

postconditions
  List of strings — verifiable system state AFTER the test completes (including cleanup).
  Examples:
    - "User session is active in the database"
    - "No new record created in the users table"
    - "Confirmation email sent to test@example.com"

gherkin_scenario
  Full Gherkin BDD block covering ALL possible scenarios for this test case.
  RULES:
    • Start with: Scenario: <title>
    • Given: system state before the action
    • When: the action performed by the actor
    • Then: the observable outcome
    • Use And / But for additional steps
    • Use concrete values from test_data (never placeholders like <email>)
    • For parametric scenarios use Scenario Outline with Examples table
    • IMPORTANT: Use single quotes ' for values inside the Gherkin text, NOT double quotes "
  Example (positive):
    Scenario: Login with valid credentials
      Given the user is on the login page
      And a user account exists with email 'user@example.com' and password 'SecurePass123!'
      When the user enters email 'user@example.com' and password 'SecurePass123!'
      And the user clicks the 'Login' button
      Then the user is redirected to the dashboard
      And a welcome message 'Hello, User' is displayed
      And a session token is stored in the database

  Example (negative):
    Scenario: Reject login with empty email
      Given the user is on the login page
      When the user enters email '' and password 'SecurePass123!'
      And the user clicks the 'Login' button
      Then an error message 'Email is required' is displayed
      And no session token is created

  Example (boundary):
    Scenario: Login with email at maximum length
      Given the user is on the login page
      And a user account exists with email 'this.is.a.very.long.email.address.with.many.characters@example.com'
      When the user enters email 'this.is.a.very.long.email.address.with.many.characters@example.com' and password 'SecurePass123!'
      And the user clicks the 'Login' button
      Then the user is redirected to the dashboard

steps
  Structured list that mirrors the Gherkin scenario above, step by step.
  Each step: order (int starting at 1), action (what the tester does), expected (what the system shows — empty string for Given/When steps).
  IMPORTANT: Use single quotes ' for values inside action and expected strings.
  Example:
    - order: 1, action: "Navigate to /login", expected: "Login page is displayed"
    - order: 2, action: "Enter email 'user@example.com'", expected: ""
    - order: 3, action: "Enter password 'SecurePass123!'", expected: ""
    - order: 4, action: "Click the 'Login' button", expected: "User is redirected to /dashboard"

test_data
  JSON object with ALL concrete values used in this test case.
  Use realistic but fictional data. NEVER use real credentials or PII.
  IMPORTANT: This is a JSON field - use standard JSON format with double quotes.
  ⚠️ CRITICAL: All values MUST be LITERAL strings - NEVER use code expressions.
  CORRECT ✅: "username": "testuser123"
  CORRECT ✅: "username": "this.is.a.long.username.for.boundary.test"
  Examples:
    Positive: {{"email": "test.user@example.com", "password": "SecurePass123!"}}
    Negative: {{"email": "", "password": "abc"}}
    Boundary: {{"email": "this.is.a.very.long.email.address.with.many.characters@example.com", "password": "ThisIsAVeryLongPasswordWithMixedChars123!"}}

expected_results
  List of final assertions that must ALL be TRUE when the test PASSES.
  IMPORTANT: Use single quotes ' for values inside these strings, NOT double quotes ".
  Examples:
    - "HTTP 200 response received within 2 seconds"
    - "User record created in the database with correct email and hashed password"
    - "Error message 'Invalid email' displayed below the email field"
    - "No session cookie set in the browser"

covered_ac_indices
  0-based indices of acceptance criteria that this test case verifies.
  Example: [0, 2] means this test covers AC[0] and AC[2].
  Every AC must appear in at least one test case's covered_ac_indices.

reasoning
  One sentence explaining which behavior this test verifies and why it matters.

covered_risk_ids
  List of risk IDs that this test case verifies or mitigates.
  Use ONLY the EXACT risk IDs listed in the ACCEPTED RISK IDs section above (e.g. RISK-1, RISK-2).
  Do NOT invent IDs. If no listed risk applies to this test case, use an empty list.
  Examples:
    - ["RISK-1", "RISK-3"]  # covers two risks
    - ["RISK-2"]             # covers one risk
    - []                     # no risk applies to this test case
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL JSON FORMATTING RULES:
- The ENTIRE output must be valid JSON that can be parsed by a JSON parser
- In ALL string fields (title, preconditions, postconditions, gherkin_scenario, steps, expected_results, reasoning):
  • Use SINGLE quotes ' for quoting values inside strings (e.g., "Enter email 'user@example.com'")
  • NEVER use double quotes " inside string values (this breaks JSON parsing)
  • The only double quotes should be the JSON field delimiters
- The test_data field is standard JSON: use double quotes normally
- covered_ac_indices, and covered_risk_ids are arrays: use standard JSON format
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES:
- Generate ONLY {scenario_type} test cases
- Each test case must be fully independent (no shared state between tests)
- Every acceptance criterion must appear in at least one covered_ac_indices list
- Negative tests MUST use INVALID data (empty, wrong format, too long, SQL injection, etc.)
- Boundary value tests MUST test LIMIT values (max_length, min_length, 0, -1, empty, null, special chars, Unicode)
- For boundary value test_data: NEVER use repetitive characters like "aaaa...".
  Instead use realistic examples:
    • Long email: "this.is.a.very.long.email.address.with.many.characters@example.com"
    • Long password: "ThisIsAVeryLongPasswordWithMixedChars123!"
    • Max length string: "Lorem ipsum dolor sit amet, consectetur adipiscing elit"
  • Keep strings under 80 characters MAXIMUM.
- No two test cases may test the exact same behavior — each must target a distinct scenario
- If similar tests exist, use DIFFERENT data or test DIFFERENT aspects
- Steps must be atomic (one user action per step)
- All field values must be in English
- All test_data values must be LITERAL strings, not code expressions
- Generate exactly {count} test case(s)
- Output ONLY the JSON object — no markdown code blocks, no extra text before or after
"""


CORRECTION_PROMPT = """You are an ISTQB-certified test analyst.

Some acceptance criteria are NOT yet covered by the existing test cases.
Generate ADDITIONAL {count} {scenario_type} test case(s) that cover the uncovered ACs below.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER STORY:
{story}

ALL ACCEPTANCE CRITERIA:
{acceptance_criteria}

UNCOVERED ACs — you MUST cover ALL of these:
{uncovered_acs}

RISK LEVEL: {risk_level}
ACCEPTED RISK IDs LINKED TO THIS USER STORY:
{risk_ids_list}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TEST TYPE: {scenario_type}
Generate exactly {count} additional test case(s) of type "{scenario_type}".
Each test case MUST cover at least one of the UNCOVERED ACs listed above.

Use the same field definitions and JSON formatting rules as before:
- title, test_type, priority, preconditions, postconditions, gherkin_scenario,
  steps, test_data, expected_results, covered_ac_indices, reasoning, covered_risk_ids
- test_type must be exactly: {scenario_type}
- covered_ac_indices must reference the indices of the UNCOVERED ACs above
  (use the same 0-based indexing as the full AC list)
- CRITICAL JSON FORMATTING: single quotes inside strings, double quotes only as JSON delimiters
- Output ONLY the JSON object — no markdown, no extra text
"""
