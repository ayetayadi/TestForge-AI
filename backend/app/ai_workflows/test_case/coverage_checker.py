"""
Pure functions for AC coverage checking per User Story.

No LLM, no I/O:
  - validate_ac_coverage  → AC coverage for ONE User Story
  - suggest_hints         → derive hints for uncovered ACs
"""

import re
import logging
from typing import Any, Dict, List

from app.ai_workflows.test_case.config import MIN_AC_COVERAGE

logger = logging.getLogger(__name__)

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
        searchable_parts = []
        
        if tc.get("title"):
            searchable_parts.append(tc["title"])
        
        gherkin = tc.get("gherkin_source") or tc.get("gherkin_scenario", "")
        if gherkin:
            searchable_parts.append(gherkin)
        
        if tc.get("expected_results"):
            searchable_parts.extend(tc["expected_results"])
        
        if tc.get("preconditions"):
            searchable_parts.extend(tc["preconditions"])
            
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
# LA SEULE FONCTION DE COUVERTURE NÉCESSAIRE
# ============================================================

def validate_ac_coverage(
    test_cases: List[Dict[str, Any]],
    acceptance_criteria: List[str],
) -> Dict[str, Any]:
    """
    AC Coverage pour UNE User Story.
    
    Formule ISTQB §4.3.2:
        (ACs avec au moins 1 TC / Total ACs) × 100
    
    Args:
        test_cases: Liste des TCs générés pour cette US
        acceptance_criteria: Liste des ACs de cette US
    
    Returns:
        {
            "is_sufficient": bool,
            "coverage_pct": float,
            "covered_count": int,
            "total_count": int,
            "uncovered": List[str],
            "uncovered_indices": List[int]
        }
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

    # Stratégie 1: Indices explicites du LLM
    for tc in test_cases:
        indices = tc.get("covered_ac_indices", [])
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(acceptance_criteria):
                covered_indices.add(idx)

    # Stratégie 2: Fallback sémantique
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

    logger.info(f"[AC COVERAGE] {covered}/{total} = {pct:.0%} (seuil={MIN_AC_COVERAGE:.0%})")

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
    Suggère des scénarios de test pour les ACs non couverts.
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