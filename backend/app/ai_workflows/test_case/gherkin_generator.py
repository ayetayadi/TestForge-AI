"""
Pure functions for Gherkin BDD manipulation.

No LLM, no I/O:
  - validate_gherkin      → check the Gherkin text has the minimum required structure
  - parse_gherkin_steps   → extract structured steps from a Gherkin scenario text
  - extract_postconditions→ derive postconditions from Then/And clauses
  - normalize_gherkin     → clean indentation and keyword casing
"""

import re
import logging
from typing import Any, Dict, List, Tuple

from app.ai_workflows.test_case.config import GHERKIN_KEYWORDS, MIN_GHERKIN_STEPS

logger = logging.getLogger(__name__)

# Regex: line starting with a Gherkin keyword
_STEP_PATTERN = re.compile(
    r"^\s*(Given|When|Then|And|But)\s+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_SCENARIO_PATTERN = re.compile(r"^\s*Scenario\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def validate_gherkin(text: str) -> Tuple[bool, List[str]]:
    """
    Check that a Gherkin scenario has the minimum valid structure.

    Returns:
        (is_valid, issues)  — issues is empty when is_valid is True
    """
    if not text or len(text.strip()) < 20:
        return False, ["Gherkin scenario is empty or too short"]

    issues: List[str] = []
    tl = text.lower()

    if not re.search(r"given", tl):
        issues.append("Missing Given clause")
    if not re.search(r"when", tl):
        issues.append("Missing When clause")
    if not re.search(r"then", tl):
        issues.append("Missing Then clause")

    steps = _STEP_PATTERN.findall(text)
    if len(steps) < MIN_GHERKIN_STEPS:
        issues.append(f"Too few steps: {len(steps)} found, minimum {MIN_GHERKIN_STEPS}")

    return len(issues) == 0, issues


def parse_gherkin_steps(gherkin_text: str) -> List[Dict[str, Any]]:
    """
    Convert a Gherkin scenario text into a structured steps list.

    Returns:
        [{"order": 1, "action": "Navigate to /login", "expected": ""}]

    The "expected" field is populated for Then/And steps that follow a When.
    Action steps (Given/When) have expected="".
    """
    steps: List[Dict[str, Any]] = []
    matches = _STEP_PATTERN.findall(gherkin_text)

    in_then_block = False
    order = 1

    for keyword, text in matches:
        kw = keyword.strip().lower()
        step_text = text.strip()

        if kw == "then":
            in_then_block = True

        if in_then_block and kw in ("then", "and", "but"):
            steps.append({
                "order": order,
                "action": f"{keyword} {step_text}",
                "expected": step_text,
            })
        else:
            in_then_block = False
            steps.append({
                "order": order,
                "action": f"{keyword} {step_text}",
                "expected": "",
            })

        order += 1

    return steps


def extract_postconditions(gherkin_text: str) -> List[str]:
    """
    Extract Then/And clauses as postconditions (observable state after test).
    """
    postconditions: List[str] = []
    in_then = False

    for keyword, text in _STEP_PATTERN.findall(gherkin_text):
        kw = keyword.strip().lower()
        if kw == "then":
            in_then = True
        if in_then and kw in ("then", "and"):
            postconditions.append(text.strip())
        elif kw not in ("and", "but"):
            in_then = False

    return postconditions


def normalize_gherkin(text: str) -> str:
    """
    Normalize indentation and keyword casing in a Gherkin scenario.
    """
    lines = text.strip().splitlines()
    normalized: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Capitalize Gherkin keywords
        upper_match = re.match(
            r"^(scenario|given|when|then|and|but)(\s*:?\s*)(.*)$",
            stripped,
            re.IGNORECASE,
        )
        if upper_match:
            kw = upper_match.group(1).capitalize()
            rest = upper_match.group(3)
            if kw.lower() == "scenario":
                normalized.append(f"Scenario: {rest}")
            else:
                normalized.append(f"  {kw} {rest}")
        else:
            normalized.append(f"  {stripped}")

    return "\n".join(normalized)


def build_tc_code(index: int) -> str:
    return f"TC-{index:03d}"
