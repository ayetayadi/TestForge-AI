"""Pydantic schemas for TestSuite — list, detail, traceability matrix, dependency graph."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ============================================================
# EMBEDDED: TEST CASE
# ============================================================

class EmbeddedTestCaseSchema(BaseModel):
    id: str
    tc_code: str
    title: str
    description: Optional[str] = None
    test_type: Optional[str] = None
    priority: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    preconditions: List[str] = Field(default_factory=list)
    postconditions: List[str] = Field(default_factory=list)
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    gherkin_source: Optional[str] = None
    test_data: Optional[Dict[str, Any]] = Field(default_factory=dict)
    expected_results: List[str] = Field(default_factory=list)
    risk_ids: List[str] = Field(default_factory=list)
    execution_order: Optional[int] = None
    user_story_id: Optional[str] = None
    test_suite_id: Optional[str] = None  # ✅ Ajouté
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None  # ✅ Ajouté
    # Computed priority score for display
    priority_score: int = Field(0, description="Composite score: risk weight + coverage + ac_index")

    class Config:
        from_attributes = True


# ============================================================
# EMBEDDED: RISK
# ============================================================

class EmbeddedRiskSchema(BaseModel):
    id: str
    description: str
    level: Optional[str] = None
    risk_score: Optional[float] = None
    probability: Optional[float] = None
    impact: Optional[int] = None
    mitigation: Optional[str] = None
    is_accepted: Optional[bool] = False  # ✅ Changé en Optional

    class Config:
        from_attributes = True


# ============================================================
# EMBEDDED: TEST PLAN
# ============================================================

class EmbeddedTestPlanSchema(BaseModel):
    id: str
    title: str
    status: Optional[str] = None  # ✅ Changé en Optional
    objective: Optional[str] = None
    in_scope: Optional[str] = None
    out_of_scope: Optional[str] = None
    test_types: List[str] = Field(default_factory=list)
    test_levels: List[str] = Field(default_factory=list)
    environment: Optional[str] = None
    entry_criteria: Optional[str] = None
    exit_criteria: Optional[str] = None
    approach: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    approved_at: Optional[datetime] = None
    coverage_snapshot: Optional[Dict[str, Any]] = None
    matrix_snapshot: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


# ============================================================
# COVERAGE METRICS
# ============================================================

class SuiteCoverageSchema(BaseModel):
    total_cases: int = 0
    active_cases: int = 0
    by_priority: Dict[str, int] = Field(default_factory=dict)
    by_type: Dict[str, int] = Field(default_factory=dict)
    has_gherkin: int = 0
    has_steps: int = 0
    risk_coverage_pct: float = 0.0
    uncovered_risks: int = 0
    mitigation_status: str = "not_mitigated"


# ============================================================
# TRACEABILITY MATRIX
# ============================================================

class TraceabilityACRow(BaseModel):
    """One acceptance criterion and which test cases cover it."""
    ac_index: int
    ac_text: str
    covered_by: List[str] = Field(default_factory=list, description="List of tc_code values")
    is_covered: bool = False


class TraceabilityStoryRow(BaseModel):
    """One user story with its ACs and coverage."""
    user_story_id: str
    issue_key: str
    title: str
    acceptance_criteria: List[TraceabilityACRow] = Field(default_factory=list)
    covered_cases: int = 0
    total_ac: int = 0
    coverage_pct: float = 0.0


class TraceabilityMatrixSchema(BaseModel):
    """Full traceability matrix: Stories × ACs × Test Cases."""
    rows: List[TraceabilityStoryRow] = Field(default_factory=list)
    total_stories: int = 0
    total_ac: int = 0
    covered_ac: int = 0
    global_coverage_pct: float = 0.0


# ============================================================
# DEPENDENCY GRAPH
# ============================================================

class DependencyNode(BaseModel):
    id: str
    tc_code: str
    title: str
    priority: Optional[str] = None
    test_type: Optional[str] = None
    execution_order: Optional[int] = None
    test_suite_id: Optional[str] = None  # ✅ Ajouté pour contexte


class DependencyEdge(BaseModel):
    source: str = Field(description="tc_code of source test case")
    target: str = Field(description="tc_code of target test case")
    source_id: str
    target_id: str
    dependency_type: str = Field(default="requires", description="requires | blocks | related")
    is_ai_generated: bool = True


class DependencyGraphSchema(BaseModel):
    """Directed graph of test case dependencies."""
    nodes: List[DependencyNode] = Field(default_factory=list)
    edges: List[DependencyEdge] = Field(default_factory=list)
    execution_order: List[str] = Field(
        default_factory=list,
        description="Topologically sorted tc_codes (safe execution sequence)"
    )


# ============================================================
# PRIORITY REASONING (visible in detail page)
# ============================================================

class PriorityReasoningSchema(BaseModel):
    risk_weight: int = Field(0, description="Total risk weight for this suite")
    risk_breakdown: Dict[str, int] = Field(default_factory=dict, description="Risk level → count")
    coverage_ac_count: int = Field(0, description="Number of ACs covered by this suite")
    coverage_total_ac: int = Field(0, description="Total ACs in scope")
    requirement_order: int = Field(0, description="Order based on Jira priority")
    priority_formula: str = Field("", description="Explanation of the priority calculation")
    execution_order_reason: str = Field("", description="Why this execution order")


# ============================================================
# SUITE LIST ITEM
# ============================================================

class TestSuiteListItemSchema(BaseModel):
    id: str
    test_plan_id: str
    title: str
    description: Optional[str] = None
    suite_type: Optional[str] = None
    priority: Optional[str] = None
    status: str = "draft"
    execution_order: Optional[int] = None
    is_ai_generated: bool = False
    test_case_count: int = 0
    project_name: Optional[str] = None
    project_key: Optional[str] = None
    test_plan_title: Optional[str] = None
    test_plan_status: Optional[str] = None
    risk_coverage: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TestSuiteListResponse(BaseModel):
    items: List[TestSuiteListItemSchema] = Field(default_factory=list)
    total: int = 0


# ============================================================
# SUITE DETAIL (full QA view)
# ============================================================

class TestSuiteDetailSchema(BaseModel):
    # Core
    id: str
    test_plan_id: str
    title: str
    description: Optional[str] = None
    suite_type: Optional[str] = None
    priority: Optional[str] = None
    status: str = "draft"
    execution_order: Optional[int] = None
    is_ai_generated: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Context
    test_plan: Optional[EmbeddedTestPlanSchema] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    project_key: Optional[str] = None

    # Test cases — sorted by risk→coverage→ac_index
    test_cases: List[EmbeddedTestCaseSchema] = Field(default_factory=list)

    # Risks covered by this suite
    risks: List[EmbeddedRiskSchema] = Field(default_factory=list)

    # Coverage
    risk_coverage: Optional[Dict[str, Any]] = None
    us_ac_coverages: List[Dict[str, Any]] = Field(default_factory=list)

    # Traceability matrix
    traceability_matrix: Optional[TraceabilityMatrixSchema] = None  # ✅ Changé en Optional

    # Dependency graph
    dependency_graph: Optional[DependencyGraphSchema] = None  # ✅ Changé en Optional

    # Lifecycle for QA Engineer timeline
    lifecycle: Dict[str, Any] = Field(default_factory=dict)

    # Priority reasoning
    priority_reasoning: Optional[PriorityReasoningSchema] = None

    # All suites order for comparison
    all_suites_order: List[Dict[str, Any]] = Field(default_factory=list, description="All suites with their execution order")

    class Config:
        from_attributes = True


# ============================================================
# GENERATE SUITES REQUEST / RESPONSE
# ============================================================

class GenerateTestSuitesRequest(BaseModel):
    test_plan_id: str = Field(..., description="Parent Test Plan ID")
    strategy: str = Field("risk_level", description="risk_level | test_type | feature | mixed")
    project_name: str = Field("", description="Project name for suite titles")


class GenerateTestSuitesResponse(BaseModel):
    suites: List[Dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    strategy: str = "risk_level"
    workflow_status: str = "success"
    error: Optional[str] = None  # ✅ Ajouté pour les erreurs


# ============================================================
# ASSIGN / UNASSIGN TEST CASE
# ============================================================

class AssignTestCaseRequest(BaseModel):
    test_case_id: str
    suite_id: str


class UnassignTestCaseRequest(BaseModel):
    test_case_id: str


# ============================================================
# UPDATE SUITE
# ============================================================

class UpdateTestSuiteRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    suite_type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    execution_order: Optional[int] = None