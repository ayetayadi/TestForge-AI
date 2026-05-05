"""
Pure functions for test suite organization.

No LLM, no I/O:
  - group_by_test_type   → one suite per test type (positive, negative, edge_case)
  - assign_suite_order   → set execution_order on suites
  - build_suite_record   → assemble a TestSuite-compatible dict
"""

import logging
from typing import Any, Dict, List, Optional

from app.ai_workflows.test_suite.config import (
    MIN_TC_PER_SUITE,
    SUITE_EXECUTION_ORDER,
    VALID_SUITE_TYPES,
)

logger = logging.getLogger(__name__)


# ============================================================
# GROUPING STRATEGIES
# ============================================================

def group_by_test_type(test_cases: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group test cases by test_type: positive, negative, edge_case."""
    groups: Dict[str, List] = {}
    for tc in test_cases:
        t = (tc.get("test_type") or "positive").lower()
        groups.setdefault(t, []).append(tc)
    return {k: v for k, v in groups.items() if len(v) >= MIN_TC_PER_SUITE}

def pick_suite_type(group_key: str) -> str:
    """Retourne le type de scénario comme suite_type."""
    if group_key in ("positive", "negative", "boundary"):
        return group_key
    return "feature"

def pick_priority(group_key: str, test_cases: List[Dict[str, Any]]) -> str:
    """Derive suite priority from its group key or test case priorities."""
    key = group_key.lower()
    if "critical" in key:
        return "critical"
    if "high" in key or any(tc.get("priority") == "critical" for tc in test_cases):
        return "high"
    if "medium" in key:
        return "medium"
    return "low"


# Test type → execution rank (positive first, then negative, then boundary)
_TEST_TYPE_ORDER: dict[str, int] = {
    "positive": 10,
    "negative": 20,
    "boundary": 30,
    "edge_case": 30,
    "edge": 30,
}


def assign_suite_order(suites: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort suites by execution_order.
    - By suite_type: smoke=0, critical/security=1, high=2, medium=3, low=4, regression=5
    - By test_type grouping: positive=10, negative=20, boundary=30
    """
    def _order_key(suite: Dict[str, Any]) -> int:
        st = (suite.get("suite_type") or "").lower()
        gk = (suite.get("_group_key") or "").lower()

        # Smoke always first
        if st == "smoke":
            return SUITE_EXECUTION_ORDER.get("smoke", 0)

        # Test_type grouping (group_key is the test_type value)
        for ttype, rank in _TEST_TYPE_ORDER.items():
            if gk == ttype or gk.startswith(ttype):
                return rank

        # Suite type order
        if st in SUITE_EXECUTION_ORDER:
            return SUITE_EXECUTION_ORDER[st]

        # Group key contains risk level
        for level, order in SUITE_EXECUTION_ORDER.items():
            if level in gk:
                return order

        return 99

    ordered = sorted(suites, key=_order_key)
    for i, suite in enumerate(ordered, start=1):
        suite["execution_order"] = i
    return ordered


def build_suite_record(
    group_key: str,
    test_cases: List[Dict[str, Any]],
    test_plan_id: str,
    title: str = "",
    description: str = "",
    suite_type: Optional[str] = None,
    priority: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a dict ready for TestSuite persistence, plus the list of tc_codes to assign.
    """
    resolved_type = suite_type or pick_suite_type(group_key, test_cases)
    if resolved_type not in VALID_SUITE_TYPES:
        resolved_type = "feature"

    resolved_priority = priority or pick_priority(group_key, test_cases)
    tc_codes = [tc.get("tc_code", "") for tc in test_cases if tc.get("tc_code")]

    return {
        "test_plan_id": test_plan_id,
        "title": title or f"Suite — {group_key.replace('_', ' ').title()}",
        "description": description,
        "suite_type": resolved_type,
        "priority": resolved_priority,
        "is_ai_generated": True,
        "execution_order": None,     # set by assign_suite_order
        "status": "draft",
        "_group_key": group_key,
        "_tc_codes": tc_codes,       # not a DB column — used by service to link TCs
        "_tc_count": len(test_cases),
    }
