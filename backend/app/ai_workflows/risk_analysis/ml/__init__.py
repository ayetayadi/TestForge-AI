"""
Risk-Based Testing — Analyse de risque des User Stories.

Basé sur le document RBT :
  Risk = Probability (1-5) × Impact (1-5) = Score (1-25)

Pipeline :
  1. ML Predictor → P et I
  2. Calculator → Score, Priorité, Effort
  3. LLM Explainer → Description, Mitigation, Reasoning
"""

from .pipeline import RiskAnalysisPipeline, get_pipeline, reset_pipeline, analyse_stories_batch
from .calculator import compute_risk_score, classify_priority, compute_full_result
from .config import (
    PROBABILITY_MIN, PROBABILITY_MAX,
    IMPACT_MIN, IMPACT_MAX,
    PRIORITY_CRITICAL_MIN, PRIORITY_HIGH_MIN, PRIORITY_MEDIUM_MIN,
    EFFORT_ALLOCATION, TEST_DEPTH,
)

__all__ = [
    # Pipeline
    "RiskAnalysisPipeline",
    "get_pipeline",
    "reset_pipeline",
    # Calculator
    "compute_risk_score",
    "classify_priority",
    "compute_full_result",
    # Config
    "PROBABILITY_MIN",
    "PROBABILITY_MAX",
    "IMPACT_MIN",
    "IMPACT_MAX",
    "PRIORITY_CRITICAL_MIN",
    "PRIORITY_HIGH_MIN",
    "PRIORITY_MEDIUM_MIN",
    "EFFORT_ALLOCATION",
    "TEST_DEPTH",
]