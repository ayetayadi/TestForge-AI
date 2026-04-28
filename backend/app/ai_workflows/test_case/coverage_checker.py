"""
Pure functions for acceptance criteria coverage checking.

No LLM, no I/O:
  - check_ac_coverage   → compute what percentage of ACs are covered
  - find_uncovered_acs  → identify which ACs have no matching test case
  - suggest_hints       → derive hints for missing test types
"""

import re
import logging
from typing import Any, Dict, List

from app.ai_workflows.test_case.config import MIN_AC_COVERAGE

logger = logging.getLogger(__name__)


# ============================================================
# HELPERS
# ============================================================

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "in", "on", "at", "to", "and", "or", "of",
    "le", "la", "les", "un", "une", "des", "est", "dans", "sur", "et", "ou", "de", "du",
}


def _keywords(text: str) -> set:
    words = re.findall(r"\b\w{3,}\b", text.lower())
    return {w for w in words if w not in _STOP_WORDS}


def _ac_is_covered(ac: str, test_cases: List[Dict[str, Any]]) -> bool:
    """
    Return True if at least one test case covers this AC.

    Strategy 1: explicit covered_ac_indices set by LLM.
    Strategy 2: keyword overlap ≥ 45% between AC and test case content.
    """
    ac_idx = None
    # We can't know the index here, so fall back to keyword matching
    ac_kw = _keywords(ac)
    if not ac_kw:
        return True

    for tc in test_cases:
        # Check explicit coverage declared by LLM
        covered_indices = tc.get("covered_ac_indices", [])
        if covered_indices:
            # We'll validate this at the pipeline level where we have the index
            pass

        searchable = " ".join(filter(None, [
            tc.get("title", ""),
            tc.get("gherkin_source", ""),
            " ".join(tc.get("expected_results", [])),
            " ".join(tc.get("preconditions", [])),
            " ".join(tc.get("postconditions", [])),
        ]))
        tc_kw = _keywords(searchable)
        if ac_kw and tc_kw:
            overlap = len(ac_kw & tc_kw) / len(ac_kw)
            if overlap >= 0.45:
                return True

    return False


# ============================================================
# PUBLIC API
# ============================================================

def check_ac_coverage(
    test_cases: List[Dict[str, Any]],
    acceptance_criteria: List[str],
) -> Dict[str, Any]:
    """
    Compute coverage: what percentage of ACs have at least one test case.

    Returns:
        is_sufficient: bool (True if ≥ MIN_AC_COVERAGE)
        coverage_pct: float
        covered_count: int
        total_count: int
        uncovered: List[str]
    """
    if not acceptance_criteria:
        return {
            "is_sufficient": True,
            "coverage_pct": 1.0,
            "covered_count": 0,
            "total_count": 0,
            "uncovered": [],
        }

    uncovered = [ac for ac in acceptance_criteria if not _ac_is_covered(ac, test_cases)]
    total = len(acceptance_criteria)
    covered = total - len(uncovered)
    pct = covered / total

    logger.info(f"[COVERAGE] {covered}/{total} ACs covered = {pct:.0%} (threshold={MIN_AC_COVERAGE:.0%})")

    return {
        "is_sufficient": pct >= MIN_AC_COVERAGE,
        "coverage_pct": round(pct, 3),
        "covered_count": covered,
        "total_count": total,
        "uncovered": uncovered,
    }


def validate_explicit_coverage(
    test_cases: List[Dict[str, Any]],
    acceptance_criteria: List[str],
) -> Dict[str, Any]:
    """
    Use the LLM-provided covered_ac_indices for precise coverage tracking.
    Falls back to keyword matching for test cases without explicit indices.
    """
    covered_indices: set = set()

    for tc in test_cases:
        indices = tc.get("covered_ac_indices", [])
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(acceptance_criteria):
                covered_indices.add(idx)

    # For test cases without explicit indices, use keyword fallback
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

    return {
        "is_sufficient": pct >= MIN_AC_COVERAGE,
        "coverage_pct": round(pct, 3),
        "covered_count": covered,
        "total_count": total,
        "uncovered": uncovered_acs,
        "uncovered_indices": uncovered_indices,
    }


def suggest_hints(uncovered_acs: List[str]) -> List[str]:
    """
    Derive test scenario hints for uncovered ACs.
    Returns a list of short hints (used as feedback in logs / UI).
    """
    hints: List[str] = []
    for ac in uncovered_acs[:5]:
        acl = ac.lower()
        if any(w in acl for w in ["invalid", "invalide", "wrong", "incorrect"]):
            hints.append(f"Add a negative test for: {ac[:60]}")
        elif any(w in acl for w in ["empty", "vide", "null", "missing"]):
            hints.append(f"Add an edge case for empty/null input: {ac[:60]}")
        elif any(w in acl for w in ["maximum", "minimum", "limit", "max", "min"]):
            hints.append(f"Add a boundary test for: {ac[:60]}")
        else:
            hints.append(f"Add a test case covering: {ac[:60]}")
    return hints
