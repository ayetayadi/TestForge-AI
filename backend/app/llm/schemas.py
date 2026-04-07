from pydantic import BaseModel
from typing import List, Dict


class InvestDetail(BaseModel):
    score: float
    reason: str


class AnalysisResult(BaseModel):
    llm_score: float
    invest_details: Dict[str, InvestDetail]
    llm_issues: List[str]
    llm_suggestions: List[str]
    justification: str


class EvaluationResult(BaseModel):
    llm_score: float
    llm_issues: List[str]
    llm_suggestions: List[str]
    justification: str


class RefinementResult(BaseModel):
    improved_story: str | None
    acceptance_criteria: List[str]