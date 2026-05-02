"""Pydantic schemas for Risk model (ISTQB)."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


# ============================================================
# BASE SCHEMA
# ============================================================

class RiskBase(BaseModel):
    """Base schema with common attributes."""

    description: str = Field(..., min_length=3, max_length=5000)
    mitigation: Optional[str] = Field(None, max_length=5000)
    reasoning: Optional[str] = Field(None, max_length=10000)
    probability: float = Field(0.5, ge=0.1, le=0.9)
    impact: int = Field(3, ge=1, le=5)
    is_ai_generated: bool = True
    is_accepted: Optional[bool] = None
    
    @field_validator("probability")
    @classmethod
    def validate_probability(cls, v: float) -> float:
        """ISTQB: probability between 0.1 and 0.9"""
        return round(v, 2)
    
    @field_validator("impact")
    @classmethod
    def validate_impact(cls, v: int) -> int:
        """ISTQB: impact between 1 and 5"""
        return v
    
    def compute_risk_score(self) -> float:
        """P × I as per ISTQB quantitative approach (§5.2.3 page 267)"""
        return round(self.probability * self.impact, 2)
    
    def compute_level(self) -> str:
        """Classify risk level based on score (ISTQB matrix)"""
        score = self.compute_risk_score()
        if score >= 4.0:
            return "critical"
        if score >= 2.5:
            return "high"
        if score >= 1.0:
            return "medium"
        return "low"


# ============================================================
# CREATE / UPDATE SCHEMAS
# ============================================================

class RiskCreate(RiskBase):
    """Schema for creating a new Risk."""

    user_story_id: str = Field(..., min_length=36, max_length=36)
    source: Optional[str] = "original"
    source_version_id: Optional[str] = None
    source_story_text: Optional[str] = None
    source_acceptance_criteria: Optional[str] = None


class RiskUpdate(BaseModel):
    """Schema for updating an existing Risk (all fields optional)."""
    
    description: Optional[str] = Field(None, min_length=3, max_length=5000)
    mitigation: Optional[str] = Field(None, max_length=5000)
    probability: Optional[float] = Field(None, ge=0.1, le=0.9)
    impact: Optional[int] = Field(None, ge=1, le=5)
    is_ai_generated: Optional[bool] = None
    is_accepted: Optional[bool] = None


# ============================================================
# RESPONSE SCHEMA
# ============================================================

class RiskResponse(RiskBase):
    """Schema for API responses."""

    id: str
    user_story_id: Optional[str] = None
    user_story_key: Optional[str] = None
    user_story_title: Optional[str] = None
    risk_score: float
    level: str
    created_at: datetime
    source: Optional[str] = "original"
    source_version_id: Optional[str] = None
    source_story_text: Optional[str] = None
    source_acceptance_criteria: Optional[str] = None

    class Config:
        from_attributes = True


# ============================================================
# FILTERS & LIST SCHEMAS
# ============================================================

class RiskFilters(BaseModel):
    """Filters for listing risks."""
    user_story_id: Optional[str] = None
    level: Optional[str] = Field(None, pattern="^(critical|high|medium|low)$")
    is_accepted: Optional[bool] = None
    is_ai_generated: Optional[bool] = None
    min_risk_score: Optional[float] = Field(None, ge=0, le=4.5)
    max_risk_score: Optional[float] = Field(None, ge=0, le=4.5)


class RiskListResponse(BaseModel):
    """Response for paginated list of risks."""
    
    items: List[RiskResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================
# BATCH OPERATIONS
# ============================================================

class RiskBatchCreate(BaseModel):
    """Batch creation of risks for multiple user stories."""    
    risks: List[RiskCreate]


class RiskBatchResponse(BaseModel):
    """Response for batch operations."""
    
    created: List[RiskResponse]
    failed: List[dict]  # Contains index and error message
    total_success: int
    total_failed: int