"""
Modèles Pydantic pour le pipeline Risk Analysis.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class MLPrediction(BaseModel):
    probability: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = "unknown"


class LLMExplanation(BaseModel):
    description: str = Field(description="One concise description of the risk (2-3 sentences)")
    mitigation: str = Field(description="Concrete testing actions to reduce the risk")
    reasoning: str = Field(description="Brief reasoning: why this P and this I, and the P×I calculation")

    # The KNN gives the P/I numbers; the LLM justifies them with a factor breakdown.
    probability_factors: Dict[str, int] = Field(
        default_factory=dict,
        description="Probability sub-factors, each rated 1-5: "
                    "{story_complexity, ac_complexity, dependencies, clarity}",
    )
    impact_factors: Dict[str, int] = Field(
        default_factory=dict,
        description="Impact sub-factors, each rated 1-5: "
                    "{users_affected, revenue, safety, reputation}",
    )
    probability_reasoning: str = Field(default="", description="One sentence explaining the probability")
    impact_reasoning: str = Field(default="", description="One sentence explaining the impact")


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

    # LLM-produced justification of the KNN P/I scores
    probability_factors: Optional[dict] = None
    impact_factors: Optional[dict] = None
    probability_reasoning: Optional[str] = None
    impact_reasoning: Optional[str] = None

    is_ai_generated: bool = True
    is_accepted: Optional[bool] = None
    ml_confidence: float = 0.0
    source: str = "unknown"
    workflow_status: str = "success"
    error: Optional[str] = None
