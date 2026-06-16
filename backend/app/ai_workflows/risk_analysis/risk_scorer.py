"""
Pure functions for risk scoring — ISTQB Risk-Based Testing.

Scale:   P (1-5) × I (1-5) = Risk Score (1-25)
Levels:  Critical ≥15 | High 9-14 | Medium 4-8 | Low 1-3

ISTQB principle: P and I are derived as the rounded average of their
respective sub-factors, not freely chosen by the LLM.
"""

import logging
from typing import Any, Dict, List, Optional

from app.ai_workflows.risk_analysis.config import (
    PROBABILITY_MIN, PROBABILITY_MAX,
    IMPACT_MIN, IMPACT_MAX,
    LEVEL_CRITICAL_MIN, LEVEL_HIGH_MIN, LEVEL_MEDIUM_MIN,
)

logger = logging.getLogger(__name__)


def compute_risk_score(probability: int, impact: int) -> int:
    """Return P × I (ISTQB: integer 1-25)."""
    return probability * impact


def classify_level(risk_score: int) -> str:
    """
    ISTQB 5×5 matrix classification:
      Critical : 15 – 25
      High     :  9 – 14
      Medium   :  4 –  8
      Low      :  1 –  3
    """
    if risk_score >= LEVEL_CRITICAL_MIN:
        return "critical"
    if risk_score >= LEVEL_HIGH_MIN:
        return "high"
    if risk_score >= LEVEL_MEDIUM_MIN:
        return "medium"
    return "low"


def clamp_values(probability: int, impact: int) -> tuple[int, int]:
    """Force P and I into the valid 1-5 range."""
    p = max(PROBABILITY_MIN, min(PROBABILITY_MAX, int(probability)))
    i = max(IMPACT_MIN, min(IMPACT_MAX, int(impact)))
    return p, i


def _avg_factors(factors: dict) -> Optional[int]:
    """
    Compute round(avg(factor_values)) from a sub-factor dict.
    Returns None if factors is empty or contains no numeric values.
    """
    values = [v for v in factors.values() if isinstance(v, (int, float))]
    if not values:
        return None
    return max(1, min(5, round(sum(values) / len(values))))


def get_test_depth(level: str) -> str:
    """
    Recommended test depth per ISTQB §5.2.4 effort allocation:
      Critical → comprehensive  (60% effort)
      High     → thorough       (25% effort)
      Medium   → standard       (10% effort)
      Low      → smoke           (5% effort)
    """
    return {
        "critical": "comprehensive",
        "high":     "thorough",
        "medium":   "standard",
        "low":      "smoke",
    }.get(level, "standard")


def build_risk_record(
    probability: int,
    impact: int,
    description: str,
    mitigation: Optional[str],
    reasoning: str = "",
    probability_factors: Optional[dict] = None,
    impact_factors: Optional[dict] = None,
    probability_reasoning: Optional[str] = None,
    impact_reasoning: Optional[str] = None,
    test_depth: Optional[str] = None,
    user_story_id: Optional[str] = None,
    test_plan_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a risk record ready for persistence.

    ISTQB enforcement:
      - If sub-factors are provided, P and I are OVERRIDDEN by
        round(avg(sub-factors)) to guarantee mathematical consistency.
      - The LLM's raw P/I is used only when sub-factors are absent.
    """
    p, i = clamp_values(probability, impact)

    # Override P from sub-factor average (ISTQB: P = avg of its 4 factors)
    if probability_factors:
        derived_p = _avg_factors(probability_factors)
        if derived_p is not None:
            if derived_p != p:
                logger.debug(
                    f"[SCORER] P override: LLM={p} → sub-factor avg={derived_p}"
                )
            p = derived_p

    # Override I from sub-factor average (ISTQB: I = avg of its 4 factors)
    if impact_factors:
        derived_i = _avg_factors(impact_factors)
        if derived_i is not None:
            if derived_i != i:
                logger.debug(
                    f"[SCORER] I override: LLM={i} → sub-factor avg={derived_i}"
                )
            i = derived_i

    score = compute_risk_score(p, i)
    level = classify_level(score)
    final_test_depth = test_depth or get_test_depth(level)

    return {
        "user_story_id":        user_story_id,
        "test_plan_id":         test_plan_id,
        "description":          description,
        "mitigation":           mitigation or "",
        "probability":          p,
        "impact":               i,
        "risk_score":           score,
        "level":                level,
        "probability_factors":  probability_factors,
        "impact_factors":       impact_factors,
        "probability_reasoning": probability_reasoning or "",
        "impact_reasoning":      impact_reasoning or "",
        "test_depth":           final_test_depth,
        "is_ai_generated":      True,
        "is_accepted":          None,
        "reasoning":            reasoning,
    }
