"""Pydantic schemas for TestCase."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============================================================
# SUB-SCHEMAS POUR STORY DETAILS & RISKS
# ============================================================

class ApprovedVersionInfo(BaseModel):
    """Infos sur la version approuvée de l'US."""
    id: str
    version_number: int
    decision_status: str
    improved_story: str
    final_score: Optional[float] = None
    testability_score: Optional[float] = None
    is_testable: Optional[bool] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class StoryDetailsInfo(BaseModel):
    """Détails sur la story utilisée (originale ou approuvée)."""
    source: Optional[str] = None  # "original" | "approved"
    version_number: Optional[int] = None
    story_text: Optional[str] = None
    acceptance_criteria: List[str] = Field(default_factory=list)
    has_approved_version: bool = False
    approved_version: Optional[ApprovedVersionInfo] = None


class RiskInfo(BaseModel):
    """Infos sur un risque lié à l'US."""
    id: str
    description: str
    mitigation: Optional[str] = None
    probability: float
    impact: int
    risk_score: float
    level: str
    is_accepted: Optional[bool] = None
    is_ai_generated: bool = True
    source: Optional[str] = None
    source_story_text: Optional[str] = None
    created_at: Optional[str] = None


# ============================================================
# RESPONSE SCHEMA
# ============================================================

class TestCaseResponse(BaseModel):
    """Schema for API responses (aligné avec format_for_frontend)."""
    id: str
    tc_code: str
    title: str
    description: Optional[str] = None
    test_type: Optional[str] = None
    priority: Optional[str] = None
    
    # Suite & Plan
    test_suite_id: Optional[str] = None     
    test_suite_title: Optional[str] = None
    test_plan_id: Optional[str] = None
    test_plan_title: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    
    # ✅ Infos US (remontées via scope_refs du plan)
    user_story_id: Optional[str] = None
    issue_key: Optional[str] = None
    user_story_title: Optional[str] = None
    sprint: Optional[str] = None
    epic_key: Optional[str] = None
    epic_name: Optional[str] = None
    
    # ✅ NOUVEAUX CHAMPS - Story Details & Risks
    story_details: Optional[StoryDetailsInfo] = None
    risks: List[RiskInfo] = Field(default_factory=list)
    risks_count: int = 0
    
    # Contenu structuré
    preconditions: List[str] = Field(default_factory=list)
    postconditions: List[str] = Field(default_factory=list)
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    gherkin_source: Optional[str] = None
    test_data: Optional[Dict[str, Any]] = None
    expected_results: List[str] = Field(default_factory=list)
    locators: Optional[List[Dict[str, Any]]] = None
    execution_order: Optional[int] = None
    estimated_duration: Optional[int] = None
    excluded_from_run: bool = False
    # Couverture des critères d'acceptation (ISTQB §1.4 — traçabilité RTM)
    covered_ac_indices: List[int] = Field(default_factory=list)
    ac_coverage_reasoning: Optional[str] = None
    active_playwright_script_id: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================
# CREATE / UPDATE SCHEMAS
# ============================================================

class TestCaseCreate(BaseModel):
    """Schema for creating a new TestCase."""
    tc_code: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    test_type: Optional[str] = None
    priority: Optional[str] = None
    user_story_id: Optional[str] = None
    test_plan_id: Optional[str] = None
    test_suite_id: Optional[str] = None
    preconditions: List[str] = Field(default_factory=list)
    postconditions: List[str] = Field(default_factory=list)
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    gherkin_source: Optional[str] = None
    test_data: Optional[Dict[str, Any]] = None
    expected_results: List[str] = Field(default_factory=list)
    locators: Optional[List[Dict[str, Any]]] = None
    execution_order: Optional[int] = None
    estimated_duration: Optional[int] = None


class TestCaseUpdate(BaseModel):
    """Schema for updating an existing TestCase."""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    test_type: Optional[str] = None
    priority: Optional[str] = None
    user_story_id: Optional[str] = None
    test_plan_id: Optional[str] = None
    test_suite_id: Optional[str] = None
    preconditions: Optional[List[str]] = None
    postconditions: Optional[List[str]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    gherkin_source: Optional[str] = None
    test_data: Optional[Dict[str, Any]] = None
    expected_results: Optional[List[str]] = None
    locators: Optional[List[Dict[str, Any]]] = None
    execution_order: Optional[int] = None
    estimated_duration: Optional[int] = None
    excluded_from_run: Optional[bool] = None
    is_active: Optional[bool] = None


# ============================================================
# REQUEST SCHEMAS (pour les routes)
# ============================================================

class CreateTestCaseRequest(BaseModel):
    """Request for POST /test-cases."""
    tc_code: Optional[str] = None
    title: str
    description: Optional[str] = None
    test_type: Optional[str] = None
    priority: Optional[str] = None
    user_story_id: Optional[str] = None
    test_plan_id: Optional[str] = None
    test_suite_id: Optional[str] = None
    preconditions: Optional[List[str]] = Field(default_factory=list)
    postconditions: Optional[List[str]] = Field(default_factory=list)
    steps: Optional[List[Dict]] = Field(default_factory=list)
    gherkin_source: Optional[str] = None
    test_data: Optional[Dict] = None
    expected_results: Optional[List[str]] = Field(default_factory=list)


class UpdateTestCaseRequest(BaseModel):
    """Request for PUT /test-cases/{id}."""
    title: Optional[str] = None
    description: Optional[str] = None
    test_type: Optional[str] = None
    priority: Optional[str] = None
    user_story_id: Optional[str] = None
    test_plan_id: Optional[str] = None
    test_suite_id: Optional[str] = None
    preconditions: Optional[List[str]] = None
    postconditions: Optional[List[str]] = None
    steps: Optional[List[Dict]] = None
    gherkin_source: Optional[str] = None
    test_data: Optional[Dict] = None
    expected_results: Optional[List[str]] = None
    execution_order: Optional[int] = None
    is_active: Optional[bool] = None


# ============================================================
# LIST RESPONSE
# ============================================================

class TestCaseListResponse(BaseModel):
    """Response for paginated list of test cases."""
    items: List[TestCaseResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============================================================
# GENERATION SCHEMAS
# ============================================================

class GenerateTestCasesRequest(BaseModel):
    """Request for generating test cases."""
    test_plan_id: str                     
    test_suite_id: Optional[str] = None      
    risk_level: Optional[str] = None
    risk_score: Optional[float] = None
    risk_description: Optional[str] = None


class GeneratedTestCaseResponse(BaseModel):
    id: str
    tc_code: str
    title: str
    test_type: Optional[str] = None
    priority: Optional[str] = None
    preconditions: List[str] = Field(default_factory=list)
    postconditions: List[str] = Field(default_factory=list)
    gherkin_source: Optional[str] = None
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    test_data: Dict[str, Any] = Field(default_factory=dict)
    expected_results: List[str] = Field(default_factory=list)
    test_plan_id: Optional[str] = None
    test_suite_id: Optional[str] = None
    execution_order: Optional[int] = None
    estimated_duration: Optional[int] = None
    is_active: bool = True
    created_at: Optional[str] = None


class GenerateTestCasesResponse(BaseModel):
    count: int
    test_plan_id: str                          
    test_suite_id: Optional[str] = None        
    workflow_status: str
    feature_gherkin: str = ""
    coverage_hints: List[str] = Field(default_factory=list)
    test_cases: List[GeneratedTestCaseResponse] = Field(default_factory=list)
    error: Optional[str] = None


class AsyncTcJobResponse(BaseModel):
    job_id: str
    test_plan_id: str                      
    test_suite_id: Optional[str] = None      
    status: str = "queued"