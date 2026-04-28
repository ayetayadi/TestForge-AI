"""
Pure functions for  risk scoring.

No LLM, no I/O — only deterministic calculations.

  - compute_risk_score   → P × I
  - classify_level       → critical / high / medium / low
  - clamp_values         → enforce bounds on P and I
  - estimate_baseline    → derive a hint from Jira signals (used in prompt context only)
"""

import logging
from typing import Any, Dict, List, Optional

from app.ai_workflows.risk_analysis.config import (
    PROBABILITY_MIN, PROBABILITY_MAX,
    IMPACT_MIN, IMPACT_MAX,
    LEVEL_CRITICAL_MIN, LEVEL_HIGH_MIN, LEVEL_MEDIUM_MIN,
    JIRA_PRIORITY_IMPACT_HINT,
)

logger = logging.getLogger(__name__)


def compute_risk_score(probability: float, impact: int) -> float:
    """Return P × I rounded to 2 decimal places."""
    return round(probability * impact, 2)


def classify_level(risk_score: float) -> str:
    """
     classification:
      Critical ≥ 4.0 | High 2.5–3.9 | Medium 1.0–2.4 | Low < 1.0
    """
    if risk_score >= LEVEL_CRITICAL_MIN:
        return "critical"
    if risk_score >= LEVEL_HIGH_MIN:
        return "high"
    if risk_score >= LEVEL_MEDIUM_MIN:
        return "medium"
    return "low"


def clamp_values(probability: float, impact: int) -> tuple[float, int]:
    """Enforce ISTQB bounds on P and I."""
    p = round(max(PROBABILITY_MIN, min(PROBABILITY_MAX, float(probability))), 2)
    i = int(max(IMPACT_MIN, min(IMPACT_MAX, int(impact))))
    return p, i


def estimate_baseline(
    jira_priority: Optional[str],
    story_points: Optional[float],
    ac_count: int,
    components: List[str],
) -> Dict[str, Any]:
    """
    Derive a rough baseline hint from Jira signals.
    This is informational context only — the LLM decides the final values.

    Returns:
        probability_hint: float
        impact_hint: int
        signals: list of strings explaining what was detected
    """
    signals: List[str] = []

    # --- Impact hint from Jira priority ---
    priority_key = (jira_priority or "medium").lower().strip()
    impact_hint = JIRA_PRIORITY_IMPACT_HINT.get(priority_key, 3)
    if jira_priority:
        signals.append(f"Jira priority '{jira_priority}' → impact hint {impact_hint}")

    # --- Probability hint from complexity signals ---
    prob = 0.3  # default baseline

    if story_points is not None:
        if story_points >= 8:
            prob += 0.25
            signals.append(f"High story points ({story_points}) → +0.25 probability")
        elif story_points >= 5:
            prob += 0.15
            signals.append(f"Medium story points ({story_points}) → +0.15 probability")
        elif story_points >= 3:
            prob += 0.05
            signals.append(f"Low story points ({story_points}) → +0.05 probability")

    if ac_count >= 6:
        prob += 0.15
        signals.append(f"Many ACs ({ac_count}) → +0.15 probability")
    elif ac_count >= 3:
        prob += 0.08
        signals.append(f"Moderate ACs ({ac_count}) → +0.08 probability")

    if len(components) >= 3:
        prob += 0.10
        signals.append(f"Multiple components ({len(components)}) → +0.10 probability (integration risk)")

    prob_hint = round(max(PROBABILITY_MIN, min(PROBABILITY_MAX, prob)), 2)

    logger.debug(f"[RISK SCORER] baseline: P={prob_hint} I={impact_hint} signals={signals}")

    return {
        "probability_hint": prob_hint,
        "impact_hint": impact_hint,
        "signals": signals,
    }


def build_risk_record(
    probability: float,
    impact: int,
    description: str,
    mitigation: Optional[str],
    user_story_id: Optional[str],
    test_plan_id: Optional[str],
    reasoning: str = "",
) -> Dict[str, Any]:
    """
    Build a dict ready to be persisted as a Risk model instance.
    Clamps values and computes risk_score + level.
    """
    p, i = clamp_values(probability, impact)
    score = compute_risk_score(p, i)
    level = classify_level(score)

    return {
        "user_story_id": user_story_id,
        "test_plan_id": test_plan_id,
        "description": description,
        "mitigation": mitigation or "",
        "probability": p,
        "impact": i,
        "risk_score": score,
        "level": level,
        "is_ai_generated": True,
        "is_accepted": None,
        "reasoning": reasoning,
    }
