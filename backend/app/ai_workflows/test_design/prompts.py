"""
LLM prompts for the test design pipeline.
"""

TEST_GENERATION_PROMPT = """You are an ISTQB-certified test design specialist.

Generate Gherkin test cases for the user story below.

USER STORY:
{story}

ACCEPTANCE CRITERIA:
{acceptance_criteria}

RISK LEVEL: {risk_level}
REQUIRED TEST CASES:
- Positive scenarios (happy path): {count_positive}
- Negative scenarios (invalid input, error paths): {count_negative}
- Edge cases (boundary values, limits): {count_edge_case}

RULES:
- Write each test case in Gherkin (Given / When / Then / And)
- Each test case must cover at least one acceptance criterion
- Positive tests validate the happy path with valid inputs
- Negative tests validate system behavior with invalid/missing inputs or forbidden actions
- Edge cases test boundary values (empty fields, max length, zero, negative numbers, special characters)
- Keep test_data concrete: use realistic but fictional values (never real emails/passwords)
- priority must be: critical | high | medium | low
- tags must be relevant keywords: smoke, regression, authentication, validation, boundary, error-handling, etc.
- steps: each step has "order" (int starting at 1), "action" (what the tester does), "expected" (what should happen)
- Keep gherkin_scenario a clean multi-line string with the full scenario block
- Do NOT repeat the same scenario twice — each test case must test a distinct behavior
- Ensure every acceptance criterion is covered by at least one test case

Generate exactly {total_count} test cases.
"""
