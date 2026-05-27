"""Pydantic schemas for TcCoverage."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class TcCoverageResponse(BaseModel):
    """Coverage record for one (test_plan, user_story, scenario_type) triplet."""
    id: str
    test_plan_id: str
    user_story_id: Optional[str] = None
    issue_key: Optional[str] = None
    user_story_title: Optional[str] = None
    scenario_type: str
    coverage_pct: float
    covered_count: int
    total_ac_count: int
    tc_count: int
    generated_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TcCoverageSummary(BaseModel):
    """Aggregated coverage across all scenario types for a (plan, user_story) pair."""
    user_story_id: Optional[str] = None
    issue_key: Optional[str] = None
    user_story_title: Optional[str] = None
    positive_pct: float = 0.0
    negative_pct: float = 0.0
    boundary_pct: float = 0.0
    total_tc_count: int = 0
    overall_pct: float = 0.0
