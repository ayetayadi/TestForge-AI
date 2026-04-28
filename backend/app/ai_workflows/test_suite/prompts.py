"""
LLM prompt for test suite naming and description.
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
