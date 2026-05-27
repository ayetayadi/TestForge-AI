"""Pydantic schemas for TestRun, TestResult and TestStepResult."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class TestStepResultResponse(BaseModel):
    id: str
    step_order: int
    step_type: str
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Dict[str, Any]] = None
    status: str
    duration: Optional[float] = None
    screenshot_b64: Optional[str] = None
    executed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TestResultResponse(BaseModel):
    id: str
    status: str
    justification: Optional[str] = None
    error_message: Optional[str] = None
    screenshot_b64: Optional[str] = None
    duration: Optional[float] = None
    step_count: Optional[int] = None

    class Config:
        from_attributes = True


class TestRunResponse(BaseModel):
    """Full test run with result and steps (ISTQB §5.3 — résultat d'exécution)."""
    id: str
    script_version_id: Optional[str] = None
    test_case_id: Optional[str] = None
    base_url: str
    browser: str
    viewport: str
    timeout_ms: int
    headless: bool
    record_video: bool
    capture_screenshots_on_failure: bool
    status: str
    duration: Optional[float] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    result: Optional[TestResultResponse] = None
    steps: List[TestStepResultResponse] = []

    class Config:
        from_attributes = True


class TestRunListResponse(BaseModel):
    """Paginated list of test runs."""
    items: List[TestRunResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TestRunCreate(BaseModel):
    """Request body to trigger a new test run."""
    script_version_id: str
    test_case_id: Optional[str] = None
    base_url: str
    browser: str = "chromium"
    viewport: str = "1920x1080"
    timeout_ms: int = 30000
    headless: bool = True
    record_video: bool = False
    capture_screenshots_on_failure: bool = True
