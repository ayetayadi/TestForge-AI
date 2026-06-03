"""
Pure functions for test suite organization.

No LLM, no I/O:
  - group_by_test_type   → one suite per test type (positive, negative, edge_case)
  - group_by_user_story  → one suite per User Story
  - topological_sort_tcs → Kahn's algorithm sort respecting explicit dependency edges
  - assign_suite_order   → set execution_order on suites
  - build_suite_record   → assemble a TestSuite-compatible dict
"""

import logging
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

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

def group_by_user_story(test_cases: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group test cases by user_story_id. Each story gets its own suite.
    TCs with no story are grouped under 'unassigned'."""
    groups: Dict[str, List] = {}
    for tc in test_cases:
        us_id = tc.get("user_story_id") or "unassigned"
        groups.setdefault(us_id, []).append(tc)
    return {k: v for k, v in groups.items() if len(v) >= MIN_TC_PER_SUITE}


def topological_sort_tcs(
    tcs: List[Any],
    dependency_edges: List[Tuple[str, str]],
    sort_key_fn: Callable[[Any], Any],
) -> List[Any]:
    """
    Kahn's algorithm topological sort respecting explicit dependency edges.

    dependency_edges: list of (source_tc_code, target_tc_code) — source runs BEFORE target.
    sort_key_fn: tiebreaker applied within the same "wave" of zero-in-degree nodes.

    TCs not referenced in any edge are still included, ordered by sort_key_fn.
    Cycles are detected and the remaining TCs are appended sorted by sort_key_fn.
    """
    def _code(tc: Any) -> str:
        return tc.tc_code if hasattr(tc, "tc_code") else tc.get("tc_code", "")

    tc_map: Dict[str, Any] = {_code(tc): tc for tc in tcs}
    valid_edges = [(s, t) for s, t in dependency_edges if s in tc_map and t in tc_map]

    adj: Dict[str, List[str]] = defaultdict(list)
    in_degree: Dict[str, int] = {code: 0 for code in tc_map}

    for src, tgt in valid_edges:
        adj[src].append(tgt)
        in_degree[tgt] += 1

    ready = sorted(
        [tc for tc in tcs if in_degree[_code(tc)] == 0],
        key=sort_key_fn,
    )

    result: List[Any] = []
    while ready:
        current = ready.pop(0)
        result.append(current)
        for neighbor_code in adj.get(_code(current), []):
            in_degree[neighbor_code] -= 1
            if in_degree[neighbor_code] == 0:
                ready.append(tc_map[neighbor_code])
                ready.sort(key=sort_key_fn)

    # Cycle fallback: append remaining TCs sorted by sort_key_fn
    processed = {_code(tc) for tc in result}
    remaining = sorted(
        [tc for tc in tcs if _code(tc) not in processed],
        key=sort_key_fn,
    )
    if remaining:
        logger.warning(
            f"[TOPO SORT] {len(remaining)} TCs in dependency cycle — appended at end"
        )
    result.extend(remaining)
    return result



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


def assign_suite_order(
    suites: List[Dict[str, Any]],
    flow_order: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """
    Sort suites by execution_order.
    Primary key (when flow_order provided): business flow rank from LLM.
    Secondary key: test_type order (positive=10, negative=20, boundary=30).
    Fallback: suite_type / group_key heuristics.
    """
    def _order_key(suite: Dict[str, Any]) -> tuple:
        st = (suite.get("suite_type") or "").lower()
        gk = (suite.get("_group_key") or "").lower()

        # Primary: LLM business flow rank (if provided)
        dominant_flow = suite.get("_dominant_flow")
        primary = 50  # default mid-range
        if flow_order and dominant_flow:
            primary = flow_order.get(dominant_flow, 50)

        # Smoke always absolute first
        if st == "smoke":
            return (0, 0)

        # Secondary: test_type order
        for ttype, rank in _TEST_TYPE_ORDER.items():
            if gk == ttype or gk.startswith(ttype):
                return (primary, rank)

        # Fallback: suite_type / group_key heuristics
        if st in SUITE_EXECUTION_ORDER:
            return (primary, SUITE_EXECUTION_ORDER[st])
        for level, order in SUITE_EXECUTION_ORDER.items():
            if level in gk:
                return (primary, order)

        return (primary, 99)

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
    resolved_type = suite_type or pick_suite_type(group_key)
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
