"""Pydantic schemas for TestExecution and TestCaseResult."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class StartExecutionRequest(BaseModel):
    """Body pour lancer une exécution de suite."""
    suite_id: str
    app_url: str
    browser: str = "chromium"
    headless: bool = True
    stop_on_failure: bool = False
    model_id: Optional[str] = None


# ============================================================
# TEST CASE RESULT
# ============================================================

class TestStepInfo(BaseModel):
    """Un step effectué pendant l'exécution d'un TC."""
    order: int
    action: str
    status: str            # passed | failed
    error: Optional[str] = None


class TestCaseResultBasic(BaseModel):
    """Vue résumée d'un TestCaseResult (pour les listes)."""
    id: str
    test_case_id: str
    execution_order: int
    status: str
    duration: Optional[float] = None
    steps_passed: int = 0
    steps_failed: int = 0

    # Infos test case (jointes)
    tc_code: Optional[str] = None
    title: Optional[str] = None

    class Config:
        from_attributes = True


class TestCaseResultDetail(TestCaseResultBasic):
    """Vue détaillée d'un TestCaseResult — inclut les steps et screenshot."""
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    justification: Optional[str] = None
    error_message: Optional[str] = None
    screenshot_b64: Optional[str] = None
    script_version_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ============================================================
# TEST EXECUTION
# ============================================================

class TestExecutionBasic(BaseModel):
    """Vue résumée d'une TestExecution (pour la liste)."""
    id: str
    suite_id: str
    suite_title: Optional[str] = None      # joint
    project_name: Optional[str] = None     # joint
    app_url: str
    browser: str
    headless: bool
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration: Optional[float] = None
    total_count:   int = 0
    passed_count:  int = 0
    failed_count:  int = 0
    skipped_count: int = 0
    error_count:   int = 0
    triggered_by_email: Optional[str] = None

    class Config:
        from_attributes = True


class TestExecutionDetail(TestExecutionBasic):
    """Vue détaillée d'une TestExecution avec tous les TC results."""
    test_case_results: List[TestCaseResultDetail] = Field(default_factory=list)


class TestExecutionListResponse(BaseModel):
    """Liste paginée d'executions + stats globales."""
    items: List[TestExecutionBasic]
    total: int
    stats: Dict[str, Any] = Field(default_factory=dict)
