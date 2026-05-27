"""
Modèles Pydantic pour le pipeline Risk Analysis.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class MLPrediction(BaseModel):
    probability: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "unknown"


class LLMExplanation(BaseModel):
    description: str
    mitigation: str
    reasoning: str


class RiskAnalysisInput(BaseModel):
    user_story: str
    acceptance_criteria: List[str] = []
    user_story_id: Optional[str] = None
    test_plan_id: Optional[str] = None


class RiskAnalysisResult(BaseModel):
    user_story_id: Optional[str] = None
    test_plan_id: Optional[str] = None

    probability: int
    impact: int
    risk_score: int
    priority: str
    effort: float
    test_depth: str
    test_techniques: List[str]

    description: str
    mitigation: str
    reasoning: str

    is_ai_generated: bool = True
    is_accepted: Optional[bool] = None
    ml_confidence: float = 0.0
    source: str = "unknown"
    workflow_status: str = "success"
    error: Optional[str] = None
