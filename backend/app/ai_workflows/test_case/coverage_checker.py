"""
Pure functions for coverage checking (AC, Risk, Requirements).

No LLM, no I/O:
  - validate_explicit_coverage  → AC coverage using LLM indices + keyword fallback
  - compute_risk_coverage       → fraction of accepted risks covered by generated TCs
  - compute_requirements_coverage → fraction of user stories that have at least 1 TC
  - suggest_hints               → derive hints for uncovered ACs
"""

import re
import logging
from typing import Any, Dict, List, Optional

from app.ai_workflows.test_case.config import MIN_AC_COVERAGE

logger = logging.getLogger(__name__)


# ============================================================
# HELPERS
# ============================================================

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "in", "on", "at", "to", "and", "or", "of",
}


def _keywords(text: str) -> set:
    words = re.findall(r"\b\w{3,}\b", text.lower())
    return {w for w in words if w not in _STOP_WORDS}

def _ac_is_covered(ac: str, test_cases: List[Dict[str, Any]]) -> bool:
    """
    Return True if at least one test case covers this AC.

    Strategy 1: explicit covered_ac_indices declared by LLM.
    Strategy 2: keyword overlap >= 45% between AC and test case content.
    """
    ac_kw = _keywords(ac)
    if not ac_kw:
        return True

    for tc in test_cases:
        # Build searchable text from multiple fields
        searchable_parts = []
        
        # Add title
        if tc.get("title"):
            searchable_parts.append(tc["title"])
        
        # Add Gherkin scenario
        gherkin = tc.get("gherkin_source") or tc.get("gherkin_scenario", "")
        if gherkin:
            searchable_parts.append(gherkin)
        
        # Add expected results
        if tc.get("expected_results"):
            searchable_parts.extend(tc["expected_results"])
        
        # Add preconditions if available
        if tc.get("preconditions"):
            searchable_parts.extend(tc["preconditions"])
            
        # Add postconditions if available
        if tc.get("postconditions"):
            searchable_parts.extend(tc["postconditions"])
        
        searchable = " ".join(filter(None, searchable_parts))
        tc_kw = _keywords(searchable)
        
        if ac_kw and tc_kw:
            overlap = len(ac_kw & tc_kw) / len(ac_kw)
            if overlap >= 0.45:
                return True

    return False

# ============================================================
# PUBLIC API
# ============================================================

def validate_explicit_coverage(
    test_cases: List[Dict[str, Any]],
    acceptance_criteria: List[str],
) -> Dict[str, Any]:
    """
    AC Coverage = (ACs with at least 1 TC / Total ACs) × 100

    Uses LLM-provided covered_ac_indices for precision; falls back to
    keyword matching for test cases without explicit indices.
    """
    if not acceptance_criteria:
        return {
            "is_sufficient": True,
            "coverage_pct": 1.0,
            "covered_count": 0,
            "total_count": 0,
            "uncovered": [],
            "uncovered_indices": [],
        }

    covered_indices: set = set()

    for tc in test_cases:
        indices = tc.get("covered_ac_indices", [])
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(acceptance_criteria):
                covered_indices.add(idx)

    # Keyword fallback for TCs without explicit indices
    tcs_without_indices = [tc for tc in test_cases if not tc.get("covered_ac_indices")]
    for i, ac in enumerate(acceptance_criteria):
        if i not in covered_indices:
            if _ac_is_covered(ac, tcs_without_indices):
                covered_indices.add(i)

    uncovered_indices = [i for i in range(len(acceptance_criteria)) if i not in covered_indices]
    uncovered_acs = [acceptance_criteria[i] for i in uncovered_indices]
    total = len(acceptance_criteria)
    covered = total - len(uncovered_acs)
    pct = covered / total if total > 0 else 1.0

    logger.info(f"[AC COVERAGE] {covered}/{total} = {pct:.0%} (threshold={MIN_AC_COVERAGE:.0%})")

    return {
        "is_sufficient": pct >= MIN_AC_COVERAGE,
        "coverage_pct": round(pct, 3),
        "covered_count": covered,
        "total_count": total,
        "uncovered": uncovered_acs,
        "uncovered_indices": uncovered_indices,
    }

def compute_risk_coverage(
    test_cases: List[Dict[str, Any]],
    total_accepted_risks: int,
    accepted_risk_ids: List[str] = None,
) -> Dict[str, Any]:
    """
    Risk Coverage = (Risks with at least 1 TC / Total accepted risks) × 100

    A risk is covered ONLY if at least one test case explicitly lists its UUID
    in covered_risk_ids AND that UUID is in the accepted_risk_ids set.
    When accepted_risk_ids is not provided any non-empty ID is accepted.
    """
    if total_accepted_risks == 0:
        return {
            "coverage_pct": 1.0,
            "covered_count": 0,
            "total_count": 0,
            "covered_risk_ids": [],
            "uncovered_risk_ids": [],
            "is_sufficient": True,
        }

    known_ids: Optional[set] = set(accepted_risk_ids) if accepted_risk_ids else None

    covered_risk_ids: set = set()
    for tc in test_cases:
        ids = tc.get("covered_risk_ids", []) or tc.get("risk_ids", [])
        for rid in ids:
            if rid and (known_ids is None or rid in known_ids):
                covered_risk_ids.add(rid)

    covered_count = len(covered_risk_ids)
    pct = covered_count / total_accepted_risks

    uncovered = (
        [rid for rid in accepted_risk_ids if rid not in covered_risk_ids]
        if accepted_risk_ids else []
    )

    logger.info(
        f"[RISK COVERAGE] {covered_count}/{total_accepted_risks} risks covered = {pct:.0%} "
        f"(uncovered: {len(uncovered)})"
    )

    return {
        "coverage_pct": round(pct, 3),
        "covered_count": covered_count,
        "total_count": total_accepted_risks,
        "covered_risk_ids": list(covered_risk_ids),
        "uncovered_risk_ids": uncovered,
        "is_sufficient": pct >= MIN_AC_COVERAGE,
    }

def compute_requirements_coverage(
    covered_us_count: int,
    total_user_stories: int,
) -> Dict[str, Any]:
    """
    Requirements Coverage = (US with at least 1 TC / Total requirements (US)) × 100
    """
    if total_user_stories == 0:
        return {
            "coverage_pct": 1.0,
            "covered_count": 0,
            "total_count": 0,
            "is_sufficient": True,
        }

    pct = covered_us_count / total_user_stories

    logger.info(
        f"[REQ COVERAGE] {covered_us_count}/{total_user_stories} user stories covered = {pct:.0%}"
    )

    return {
        "coverage_pct": round(pct, 3),
        "covered_count": covered_us_count,
        "total_count": total_user_stories,
        "is_sufficient": pct >= MIN_AC_COVERAGE,
    }


def suggest_hints(uncovered_acs: List[str]) -> List[str]:
    """
    Derive test scenario hints for uncovered ACs.
    """
    hints: List[str] = []
    for ac in uncovered_acs[:5]:
        acl = ac.lower()
        if any(w in acl for w in ["invalid", "wrong", "incorrect", "error", "fail"]):
            hints.append(f"Add a negative test for: {ac[:60]}")
        elif any(w in acl for w in ["empty", "null", "missing", "blank"]):
            hints.append(f"Add a negative test for empty/null input: {ac[:60]}")
        elif any(w in acl for w in ["maximum", "minimum", "limit", "max", "min", "length", "range", "bound"]):
            hints.append(f"Add a boundary value test for: {ac[:60]}")
        elif any(w in acl for w in ["valid", "success", "correct", "happy"]):
            hints.append(f"Add a positive test for: {ac[:60]}")
        else:
            hints.append(f"Add a test case covering: {ac[:60]}")
    return hints
