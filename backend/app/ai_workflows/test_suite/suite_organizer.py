"""
Pure functions for test suite organization.

No LLM, no I/O:
  - group_by_risk_level  → one suite per risk level (critical, high, medium, low)
  - group_by_test_type   → one suite per test type (positive, negative, edge_case)
  - group_by_feature     → one suite per epic/component
  - group_mixed          → risk level first, then test type within each level
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

def group_by_risk_level(test_cases: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group test cases by the risk level of their parent user story.
    Each test case must have a '_risk_level' key (injected by the pipeline).
    """
    groups: Dict[str, List] = {"critical": [], "high": [], "medium": [], "low": []}
    for tc in test_cases:
        level = (tc.get("_risk_level") or "medium").lower()
        if level not in groups:
            level = "medium"
        groups[level].append(tc)
    return {k: v for k, v in groups.items() if len(v) >= MIN_TC_PER_SUITE}


def group_by_test_type(test_cases: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group test cases by test_type: positive, negative, edge_case."""
    groups: Dict[str, List] = {}
    for tc in test_cases:
        t = (tc.get("test_type") or "positive").lower()
        groups.setdefault(t, []).append(tc)
    return {k: v for k, v in groups.items() if len(v) >= MIN_TC_PER_SUITE}


def group_by_feature(test_cases: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group test cases by epic name or component.
    Falls back to 'general' for test cases without an epic.
    Each test case must have '_epic' or '_component' key.
    """
    groups: Dict[str, List] = {}
    for tc in test_cases:
        feature = tc.get("_epic") or tc.get("_component") or "General"
        feature = feature.strip()[:50]
        groups.setdefault(feature, []).append(tc)
    return {k: v for k, v in groups.items() if len(v) >= MIN_TC_PER_SUITE}


def group_mixed(test_cases: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Two-level grouping: risk level → test type.
    Key format: "critical_negative", "high_positive", etc.
    """
    groups: Dict[str, List] = {}
    for tc in test_cases:
        level = (tc.get("_risk_level") or "medium").lower()
        ttype = (tc.get("test_type") or "positive").lower()
        key = f"{level}_{ttype}"
        groups.setdefault(key, []).append(tc)
    return {k: v for k, v in groups.items() if len(v) >= MIN_TC_PER_SUITE}


def pick_suite_type(group_key: str, test_cases: List[Dict[str, Any]]) -> str:
    """Infer the best suite_type from the group key and its test cases."""
    key = group_key.lower()

    # Explicit type keywords
    if "smoke" in key:
        return "smoke"
    if "security" in key or any("security" in tc.get("tags", []) for tc in test_cases):
        return "security"
    if "performance" in key or any("performance" in tc.get("tags", []) for tc in test_cases):
        return "performance"
    if "regression" in key:
        return "regression"
    if "negative" in key:
        return "negative"
    if "e2e" in key:
        return "e2e"

    # Risk level → feature suite
    if any(l in key for l in ("critical", "high", "medium", "low")):
        return "feature"

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


def assign_suite_order(suites: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort suites by execution_order:
      smoke=0, critical/security=1, high=2, medium=3, low=4, regression=5
    """
    def _order_key(suite: Dict[str, Any]) -> int:
        st = (suite.get("suite_type") or "").lower()
        gk = (suite.get("_group_key") or "").lower()
        # Check suite type first
        if st in SUITE_EXECUTION_ORDER:
            return SUITE_EXECUTION_ORDER[st]
        # Then check group key for risk level
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
