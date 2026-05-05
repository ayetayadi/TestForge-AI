"""
Pure functions for risk scoring - ALIGNED WITH ORIGINAL RISK BASED TESTING DOCUMENT.

- P (Probability): 1-5 scale
- I (Impact): 1-5 scale  
- Risk Score = P × I
- Classification: Critical (20+) / High (12-19) / Medium (6-11) / Low (1-5)
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
    """Return P × I (integer, conforme au document original)"""
    return probability * impact


def classify_level(risk_score: int) -> str:
    """
    Classification conforme au document original :
    Critical 20-25 | High 12-19 | Medium 6-11 | Low 1-5
    """
    if risk_score >= LEVEL_CRITICAL_MIN:
        return "critical"
    if risk_score >= LEVEL_HIGH_MIN:
        return "high"
    if risk_score >= LEVEL_MEDIUM_MIN:
        return "medium"
    return "low"


def clamp_values(probability: int, impact: int) -> tuple[int, int]:
    """Force P et I dans l'intervalle 1-5 (échelle document original)"""
    p = int(max(PROBABILITY_MIN, min(PROBABILITY_MAX, int(probability))))
    i = int(max(IMPACT_MIN, min(IMPACT_MAX, int(impact))))
    return p, i


def get_test_depth(level: str) -> Dict[str, Any]:
    """
    Profondeur de test recommandée selon le document original.
    """
    depth_map = {
        "critical": {
            "depth": "comprehensive",
        },
        "high": {
            "depth": "thorough",
        },
        "medium": {
            "depth": "standard",
        },
        "low": {
            "depth": "smoke",
        }
    }
    return depth_map.get(level, depth_map["low"])


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
    Build a risk record dict ready for persistence.
    
    Priority: LLM values > Static fallback based on level
    """
    p, i = clamp_values(probability, impact)
    score = compute_risk_score(p, i)
    level = classify_level(score)
    
    final_test_depth = test_depth or get_test_depth(level)["depth"]
    
    return {
        "user_story_id": user_story_id,
        "test_plan_id": test_plan_id,
        "description": description,
        "mitigation": mitigation or "",
        "probability": p,
        "impact": i,
        "risk_score": score,
        "level": level,
        "probability_factors": probability_factors,
        "impact_factors": impact_factors,
        "probability_reasoning": probability_reasoning,
        "impact_reasoning": impact_reasoning,
        "test_depth": final_test_depth,          # String, pas dict
        "is_ai_generated": True,
        "is_accepted": None,
        "reasoning": reasoning,
    }