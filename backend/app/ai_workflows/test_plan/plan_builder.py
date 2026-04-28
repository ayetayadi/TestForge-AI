"""
Pure functions for test plan construction (ISTQB §5.1.1).

No LLM, no I/O:
  - summarize_risks       → aggregate risk distribution and identify critical areas
  - recommend_test_types  → derive required test types from risk content
  - estimate_duration     → PERT 3-point estimation in working days
  - build_plan_record     → assemble the final dict for TestPlan persistence
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.ai_workflows.test_plan.config import (
    DAYS_PER_STORY,
    OVERHEAD_DAYS,
    REGRESSION_THRESHOLD,
    SECURITY_KEYWORDS,
    PERFORMANCE_KEYWORDS,
    VALID_TEST_TYPES,
    VALID_TEST_LEVELS,
    VALID_ENVIRONMENTS,
)

logger = logging.getLogger(__name__)


# ============================================================
# RISK SUMMARIZATION
# ============================================================

def summarize_risks(risks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate risk_analysis results into a summary for the LLM prompt and duration estimate.

    Returns:
        counts: {critical, high, medium, low}
        top_risks: List[str] — top 5 risk descriptions sorted by score
        risk_text: str — formatted for LLM prompt
        high_risk_ratio: float — (critical + high) / total
        all_descriptions: List[str] — all descriptions (for keyword detection)
    """
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    scored: List[tuple] = []

    for r in risks:
        level = (r.get("level") or "low").lower()
        if level in counts:
            counts[level] += 1
        score = r.get("risk_score", 0.0)
        description = r.get("description", "")
        if description:
            scored.append((score, description))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_risks = [desc for _, desc in scored[:5]]

    total = len(risks)
    high_risk_ratio = (counts["critical"] + counts["high"]) / total if total > 0 else 0.0

    risk_text = "\n".join(f"  • [{score:.1f}] {desc}" for score, desc in scored[:5]) or "  (none)"

    logger.debug(f"[PLAN BUILDER] risk summary: {counts} high_ratio={high_risk_ratio:.0%}")

    return {
        "counts": counts,
        "top_risks": top_risks,
        "risk_text": risk_text,
        "high_risk_ratio": high_risk_ratio,
        "all_descriptions": [desc for _, desc in scored],
    }


# ============================================================
# TEST TYPE RECOMMENDATION
# ============================================================

def recommend_test_types(risk_summary: Dict[str, Any], stories_text: str = "") -> Dict[str, Any]:
    """
    Derive recommended test_types and test_levels from the risk distribution and story content.

    Returns:
        test_types: List[str]
        test_levels: List[str]
        reasoning: List[str]
    """
    types: list = ["functional"]
    levels: list = ["system", "acceptance"]
    reasons: list = ["functional tests are always required"]

    all_text = (stories_text + " " + " ".join(risk_summary.get("all_descriptions", []))).lower()

    if risk_summary["high_risk_ratio"] >= REGRESSION_THRESHOLD:
        types.append("regression")
        reasons.append(f"{risk_summary['high_risk_ratio']:.0%} high/critical stories → regression required")

    counts = risk_summary["counts"]
    if counts.get("critical", 0) > 0:
        types.append("smoke")
        levels.append("integration")
        reasons.append("critical risks detected → smoke tests needed before full test run")

    if any(kw in all_text for kw in SECURITY_KEYWORDS):
        types.append("security")
        reasons.append("security-related keywords found in stories")

    if any(kw in all_text for kw in PERFORMANCE_KEYWORDS):
        types.append("performance")
        reasons.append("performance-related keywords found in stories")

    if "api" in all_text or "endpoint" in all_text or "rest" in all_text:
        types.append("api")
        levels.append("component")
        reasons.append("API usage detected in stories")

    # Deduplicate preserving order
    test_types = list(dict.fromkeys(types))
    test_levels = list(dict.fromkeys(levels))

    return {
        "test_types": test_types,
        "test_levels": test_levels,
        "reasoning": reasons,
    }


# ============================================================
# PERT 3-POINT ESTIMATION
# ============================================================

def estimate_duration(
    risk_summary: Dict[str, Any],
    story_count: int,
) -> Dict[str, Any]:
    """
    PERT estimate: E = (O + 4×M + P) / 6

    Each story contributes a number of days based on its risk level.
    Returns optimistic, realistic (PERT), pessimistic in working days.
    """
    if story_count == 0:
        return {"optimistic": 1, "realistic": 2, "pessimistic": 3, "formula": "no stories"}

    counts = risk_summary["counts"]
    total = sum(counts.values()) or story_count

    # Weight each level proportionally
    o_days = p_days = m_days = 0.0
    for level, count in counts.items():
        if level not in DAYS_PER_STORY:
            continue
        weight = count / total
        o_days += weight * DAYS_PER_STORY[level]["optimistic"] * story_count
        m_days += weight * DAYS_PER_STORY[level]["realistic"] * story_count
        p_days += weight * DAYS_PER_STORY[level]["pessimistic"] * story_count

    o_total = max(1, round(o_days + OVERHEAD_DAYS))
    m_total = max(2, round(m_days + OVERHEAD_DAYS))
    p_total = max(3, round(p_days + OVERHEAD_DAYS * 1.5))

    pert = round((o_total + 4 * m_total + p_total) / 6)

    logger.debug(f"[PLAN BUILDER] PERT: O={o_total} M={m_total} P={p_total} PERT={pert}")

    return {
        "optimistic": o_total,
        "realistic": pert,
        "pessimistic": p_total,
        "formula": f"PERT = ({o_total} + 4×{m_total} + {p_total}) / 6 = {pert} days",
    }


# ============================================================
# FINAL RECORD ASSEMBLY
# ============================================================

def sanitize_list(values: List[str], allowed: set) -> List[str]:
    """Keep only allowed values, lowercase, deduped."""
    return list(dict.fromkeys(v.lower() for v in values if v.lower() in allowed))


def build_plan_record(
    llm_output: Dict[str, Any],
    risk_summary: Dict[str, Any],
    duration: Dict[str, Any],
    project_id: str,
    scope_type: str,
    scope_refs: List[str],
    environment_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Merge LLM draft with computed data into a dict ready for TestPlan persistence.
    Sanitizes test_types, test_levels, and environment against allowed values.
    Status is set to AI_PROPOSED (waiting for tester validation).
    """
    now = datetime.now(timezone.utc)

    env = (environment_override or llm_output.get("environment", "staging")).lower()
    if env not in VALID_ENVIRONMENTS:
        env = "staging"

    test_types = sanitize_list(llm_output.get("test_types", []), VALID_TEST_TYPES)
    test_levels = sanitize_list(llm_output.get("test_levels", []), VALID_TEST_LEVELS)

    if not test_types:
        test_types = ["functional"]
    if not test_levels:
        test_levels = ["system"]

    scope = (scope_type or "manual").lower()
    if scope not in {"epic", "sprint", "release", "manual", "spec_document"}:
        scope = "manual"

    return {
        "project_id": project_id,
        "title": llm_output.get("title", "Test Plan"),
        "description": llm_output.get("description", ""),
        "objective": llm_output.get("objective", ""),
        "scope_type": scope,
        "scope_refs": scope_refs or [],
        "in_scope": llm_output.get("in_scope", ""),
        "out_of_scope": llm_output.get("out_of_scope", ""),
        "test_types": test_types,
        "test_levels": test_levels,
        "environment": env,
        "entry_criteria": llm_output.get("entry_criteria", ""),
        "exit_criteria": llm_output.get("exit_criteria", ""),
        "approach": llm_output.get("approach", ""),
        "assumptions": llm_output.get("assumptions", ""),
        "constraints": llm_output.get("constraints", ""),
        "status": "ai_proposed",
        "ai_draft_generated_at": now,
        # Extra metadata (not persisted as columns, used by the API layer)
        "_duration": duration,
        "_risk_summary": {
            "counts": risk_summary["counts"],
            "high_risk_ratio": round(risk_summary["high_risk_ratio"], 2),
            "top_risks": risk_summary["top_risks"],
        },
        "_reasoning": llm_output.get("reasoning", ""),
        "stakeholders": llm_output.get("stakeholders", ""),
        "communication": llm_output.get("communication", ""),
    }
