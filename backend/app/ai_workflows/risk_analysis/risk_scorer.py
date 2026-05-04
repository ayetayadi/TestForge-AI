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
            "techniques": ["unit", "integration", "e2e", "performance", "security"],
            "effort": "60%"
        },
        "high": {
            "depth": "thorough",
            "techniques": ["unit", "integration", "e2e"],
            "effort": "25%"
        },
        "medium": {
            "depth": "standard",
            "techniques": ["unit", "integration"],
            "effort": "10%"
        },
        "low": {
            "depth": "smoke",
            "techniques": ["smoke-tests"],
            "effort": "5%"
        }
    }
    return depth_map.get(level, depth_map["low"])


# ✅ AJOUTE CES 2 FONCTIONS MANQUANTES
def get_default_techniques(level: str) -> List[str]:
    """
    Get default test techniques based on risk level.
    Fallback si le LLM ne fournit pas les techniques.
    """
    techniques_map = {
        "critical": ["unit", "integration", "e2e", "performance", "security"],
        "high":     ["unit", "integration", "e2e"],
        "medium":   ["unit", "integration"],
        "low":      ["smoke"],
    }
    return techniques_map.get(level, ["unit"])


def get_effort_allocation(level: str) -> str:
    """
    Get effort allocation based on risk level.
    Fallback si le LLM ne fournit pas l'effort.
    """
    allocation_map = {
        "critical": "60%",
        "high":     "25%",
        "medium":   "10%",
        "low":      "5%",
    }
    return allocation_map.get(level, "10%")


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
    test_depth: Optional[str] = None,        # Du LLM (prioritaire)
    test_techniques: Optional[list] = None,  # Du LLM (prioritaire)
    effort_allocation: Optional[str] = None, # Du LLM (prioritaire)
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
    
    # ✅ Priorité LLM, fallback code statique
    final_test_depth = test_depth or get_test_depth(level)["depth"]
    final_techniques = test_techniques or get_default_techniques(level)
    final_effort = effort_allocation or get_effort_allocation(level)
    
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
        "test_techniques": final_techniques,     # List
        "effort_allocation": final_effort,       # String
        "is_ai_generated": True,
        "is_accepted": None,
        "reasoning": reasoning,
    }