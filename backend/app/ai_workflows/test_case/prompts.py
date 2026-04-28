"""
LLM prompt for Gherkin BDD test case generation (ISTQB §5.4).
"""

TEST_CASE_GENERATION_PROMPT = """You are an ISTQB-certified test analyst writing Gherkin BDD test cases.

Generate test cases for the user story below using the Gherkin BDD format (Given/When/Then).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER STORY:
{story}

ACCEPTANCE CRITERIA:
{acceptance_criteria}

RISK LEVEL: {risk_level} (risk score: {risk_score})
RISK DESCRIPTION: {risk_description}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REQUIRED TEST CASES:
  • Positive  (happy path)          : {count_positive}
  • Negative  (invalid / error path): {count_negative}
  • Edge case (boundary values)     : {count_edge_case}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIELD DEFINITIONS — fill EVERY field for EVERY test case:

title
  Short imperative sentence describing the scenario (max 100 chars).
  Examples: "Login with valid credentials", "Reject empty password field"

test_type
  One of: positive | negative | edge_case

priority
  One of: critical | high | medium | low
  (critical only for scenarios blocking core user flow)

preconditions
  List of strings — state required BEFORE the test starts.
  Examples:
    - "User account exists with email test@example.com"
    - "User is NOT logged in"
    - "Database contains at least 1 product"

postconditions
  List of strings — observable state AFTER the test completes (including cleanup).
  Examples:
    - "User session is active in the database"
    - "No new record created in users table"
    - "Email confirmation sent to test@example.com"

gherkin_scenario
  Full Gherkin block in BDD format. RULES:
    • Start with: Scenario: <title>
    • Given: system state before the action
    • When: the action the user performs
    • Then: the observable outcome
    • Use And / But for additional steps
    • Be concrete — use actual values from test_data
  Example:
    Scenario: Login with valid credentials
      Given the user is on the login page
      And the user has an account with email "user@example.com"
      When the user enters email "user@example.com" and password "SecurePass123!"
      And clicks the "Login" button
      Then the user is redirected to the dashboard
      And the welcome message "Hello, User" is displayed

steps
  Structured list matching the Gherkin steps above.
  Each step: order (int), action (string — what tester does), expected (string — what system shows)
  Example:
    - order: 1, action: "Navigate to /login", expected: "Login form is displayed"
    - order: 2, action: "Enter email 'user@example.com'", expected: "Email field populated"
    - order: 3, action: "Enter password 'SecurePass123!'", expected: "Password field shows dots"
    - order: 4, action: "Click Login button", expected: "Redirect to /dashboard"

test_data
  JSON object with concrete fictional values used in this test.
  Examples:
    {{"email": "test.user@example.com", "password": "SecurePass123!", "username": "testuser"}}
    {{"email": "", "password": "abc"}}  ← for a negative test
  Use realistic but fictional values. NEVER use real credentials or PII.

expected_results
  List of final assertions — what must be TRUE when the test PASSES.
  Examples:
    - "HTTP 200 response received"
    - "User record created in database with correct email"
    - "Error message 'Invalid email' displayed below the field"
    - "No session cookie set"

tags
  List of relevant keywords for filtering/grouping.
  Choose from: smoke, regression, authentication, validation, boundary, error-handling,
               security, performance, api, ui, database, email, file-upload, permissions
  (add 2–4 relevant tags per test case)

covered_ac_indices
  List of 0-based indices of the acceptance criteria that this test case covers.
  Example: [0, 2] means this test covers AC[0] and AC[2]

reasoning
  1 sentence explaining which behavior this test verifies and why it matters.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES:
- Each test case must be independent (no shared state between tests)
- Each acceptance criterion must be covered by at least one test case
- Negative tests must use INVALID data in test_data (empty, wrong type, too long, etc.)
- Edge cases must test BOUNDARY values (0, -1, max_length, null, special characters)
- Do NOT repeat the same scenario twice — each must test a distinct behavior
- Keep steps atomic (one user action per step)
- Generate exactly {total_count} test cases
"""
