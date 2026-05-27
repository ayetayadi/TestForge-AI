"""
Calcul du score de risque : Score = P × I
"""

from dataclasses import dataclass
from typing import List

from .config import (
    EFFORT_ALLOCATION,
    TEST_DEPTH,
    PRIORITY_CRITICAL_MIN,
    PRIORITY_HIGH_MIN,
    PRIORITY_MEDIUM_MIN,
)


@dataclass
class ScorerResult:
    probability: int
    impact: int
    risk_score: int
    priority: str
    effort: float
    test_depth: str
    test_techniques: List[str]


def get_priority(score: int) -> str:
    if score >= PRIORITY_CRITICAL_MIN:
        return "critical"
    if score >= PRIORITY_HIGH_MIN:
        return "high"
    if score >= PRIORITY_MEDIUM_MIN:
        return "medium"
    return "low"


def compute_full_result(probability: int, impact: int) -> ScorerResult:
    score = probability * impact
    priority = get_priority(score)
    depth_info = TEST_DEPTH[priority]
    return ScorerResult(
        probability=probability,
        impact=impact,
        risk_score=score,
        priority=priority,
        effort=EFFORT_ALLOCATION[priority],
        test_depth=depth_info["depth"],
        test_techniques=depth_info["techniques"],
    )
