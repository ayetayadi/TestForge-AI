"""
Evaluators for the test design pipeline.

Three plain async functions — no LLM, no agent:
  - analyze_story          → extract key behaviors and boundary hints from the story
  - validate_ac_coverage   → check that ACs are covered by generated test cases
  - compute_tc_code        → generate unique TC-XXX codes
"""

import re
import logging
from typing import Any, Dict, List

from app.ai_workflows.test_design.config import MIN_COVERAGE_THRESHOLD

logger = logging.getLogger(__name__)


# ============================================================
# PRIVATE HELPERS
# ============================================================

def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _extract_keywords(text: str) -> set:
    stop_words = {
        "the", "a", "an", "is", "are", "in", "on", "at", "to", "and", "or",
        "le", "la", "les", "un", "une", "des", "est", "dans", "sur", "et", "ou",
        "que", "qui", "de", "du", "il", "elle", "je", "user", "system",
    }
    words = re.findall(r"\b\w{3,}\b", text.lower())
    return {w for w in words if w not in stop_words}


def _ac_covered_by(ac: str, test_cases: List[Dict[str, Any]]) -> bool:
    ac_kw = _extract_keywords(ac)
    if not ac_kw:
        return True
    for tc in test_cases:
        searchable = " ".join([
            tc.get("title", ""),
            tc.get("gherkin_scenario", ""),
            " ".join(tc.get("expected_results", [])),
            " ".join(tc.get("preconditions", [])),
        ])
        tc_kw = _extract_keywords(searchable)
        overlap = len(ac_kw & tc_kw) / len(ac_kw)
        if overlap >= 0.45:
            return True
    return False


# ============================================================
# PUBLIC EVALUATORS
# ============================================================

async def analyze_story(
    story: str,
    acceptance_criteria: List[str],
) -> Dict[str, Any]:
    """
    Extract key behaviors and boundary hints for the LLM prompt.

    Returns:
        behaviors: List of inferred behaviors
        boundary_hints: List of boundary/edge hints (empty fields, max values, etc.)
        ac_count: Number of ACs
    """
    try:
        behaviors: List[str] = []
        boundary_hints: List[str] = []

        sl = story.lower()

        if any(w in sl for w in ["login", "authenticate", "sign in", "connexion", "connecter"]):
            behaviors.append("authentication flow")
        if any(w in sl for w in ["create", "add", "register", "créer", "ajouter", "enregistrer"]):
            behaviors.append("resource creation")
        if any(w in sl for w in ["delete", "remove", "supprimer", "effacer"]):
            behaviors.append("resource deletion")
        if any(w in sl for w in ["update", "edit", "modify", "modifier", "mettre à jour"]):
            behaviors.append("resource update")
        if any(w in sl for w in ["search", "filter", "find", "chercher", "filtrer", "rechercher"]):
            behaviors.append("search/filter")
        if any(w in sl for w in ["export", "download", "import", "upload"]):
            behaviors.append("file transfer")
        if any(w in sl for w in ["permission", "role", "access", "autorisation"]):
            behaviors.append("access control")

        for ac in acceptance_criteria:
            acl = ac.lower()
            if any(w in acl for w in ["minimum", "maximum", "at least", "at most", "moins de", "plus de", "au moins", "au plus"]):
                boundary_hints.append(f"boundary: {ac[:80]}")
            if any(w in acl for w in ["empty", "vide", "null", "missing", "manquant"]):
                boundary_hints.append(f"empty input: {ac[:80]}")
            if any(w in acl for w in ["invalid", "invalide", "wrong", "incorrect", "error", "erreur"]):
                boundary_hints.append(f"invalid input: {ac[:80]}")

        logger.info(f"[EVALUATOR] analyze_story: {len(behaviors)} behaviors, {len(boundary_hints)} boundary hints")
        return {
            "status": "success",
            "behaviors": behaviors,
            "boundary_hints": boundary_hints[:6],
            "ac_count": len(acceptance_criteria),
        }

    except Exception as e:
        logger.error(f"[EVALUATOR] analyze_story failed: {e}")
        return {"status": "error", "error": str(e), "behaviors": [], "boundary_hints": [], "ac_count": 0}


async def validate_ac_coverage(
    test_cases: List[Dict[str, Any]],
    acceptance_criteria: List[str],
) -> Dict[str, Any]:
    """
    Verify that generated test cases cover at least MIN_COVERAGE_THRESHOLD of ACs.

    Returns:
        is_sufficient: bool
        coverage_pct: float (0.0 – 1.0)
        uncovered_acs: list of uncovered AC texts
    """
    try:
        if not acceptance_criteria:
            return {
                "status": "success",
                "is_sufficient": True,
                "coverage_pct": 1.0,
                "uncovered_acs": [],
            }

        uncovered = [ac for ac in acceptance_criteria if not _ac_covered_by(ac, test_cases)]
        total = len(acceptance_criteria)
        covered = total - len(uncovered)
        pct = covered / total

        logger.info(f"[EVALUATOR] coverage: {covered}/{total} = {pct:.0%} (threshold={MIN_COVERAGE_THRESHOLD:.0%})")

        return {
            "status": "success",
            "is_sufficient": pct >= MIN_COVERAGE_THRESHOLD,
            "coverage_pct": round(pct, 3),
            "uncovered_acs": uncovered,
        }

    except Exception as e:
        logger.error(f"[EVALUATOR] validate_ac_coverage failed: {e}")
        return {"status": "error", "error": str(e), "is_sufficient": False, "coverage_pct": 0.0, "uncovered_acs": []}


def compute_tc_codes(test_cases: List[Dict[str, Any]], start_index: int = 1) -> List[Dict[str, Any]]:
    """Assign TC-XXX codes to test cases that do not already have one."""
    result = []
    idx = start_index
    for tc in test_cases:
        tc_copy = dict(tc)
        if not tc_copy.get("tc_code"):
            tc_copy["tc_code"] = f"TC-{idx:03d}"
        idx += 1
        result.append(tc_copy)
    return result
