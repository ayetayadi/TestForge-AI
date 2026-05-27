"""
Schema validation tests — verifies Pydantic schemas match model fields
and expose the required ISTQB traceability fields.
"""

import pytest
from datetime import datetime
from app.schemas.test_case_schema import TestCaseResponse
from app.schemas.tc_coverage_schema import TcCoverageResponse, TcCoverageSummary
from app.schemas.test_run_schema import TestRunResponse, TestResultResponse


# ─── TestCaseResponse ────────────────────────────────────────────────────────

def test_test_case_response_has_ac_coverage_fields():
    """TestCaseResponse must expose AC coverage fields for RTM (ISTQB §1.4)."""
    assert "covered_ac_indices" in TestCaseResponse.model_fields
    assert "ac_coverage_reasoning" in TestCaseResponse.model_fields
    assert "active_playwright_script_id" in TestCaseResponse.model_fields


def test_test_case_response_defaults():
    """covered_ac_indices defaults to empty list; ac_coverage_reasoning to None."""
    tc = TestCaseResponse(
        id="tc-1",
        tc_code="TC-001",
        title="Login test",
    )
    assert tc.covered_ac_indices == []
    assert tc.ac_coverage_reasoning is None
    assert tc.active_playwright_script_id is None


def test_test_case_response_with_coverage():
    """Verify covered_ac_indices and reasoning populate correctly."""
    tc = TestCaseResponse(
        id="tc-1",
        tc_code="TC-001",
        title="Login test",
        covered_ac_indices=[0, 1, 2],
        ac_coverage_reasoning="Covers AC1 (email), AC2 (password), AC3 (button)",
    )
    assert tc.covered_ac_indices == [0, 1, 2]
    assert "AC1" in tc.ac_coverage_reasoning


# ─── TcCoverageResponse ──────────────────────────────────────────────────────

def test_tc_coverage_response_required_fields():
    """TcCoverageResponse must include all coverage metrics."""
    cov = TcCoverageResponse(
        id="cov-1",
        test_plan_id="plan-1",
        scenario_type="positive",
        coverage_pct=0.75,
        covered_count=3,
        total_ac_count=4,
        tc_count=3,
        generated_at=datetime.now(),
        updated_at=datetime.now(),
    )
    assert cov.coverage_pct == 0.75
    assert cov.scenario_type == "positive"
    assert cov.user_story_id is None


def test_tc_coverage_summary_defaults():
    """TcCoverageSummary defaults all percentages to 0."""
    s = TcCoverageSummary()
    assert s.positive_pct == 0.0
    assert s.negative_pct == 0.0
    assert s.boundary_pct == 0.0
    assert s.overall_pct == 0.0


# ─── TestRunResponse ─────────────────────────────────────────────────────────

def test_test_run_response_has_test_case_id():
    """TestRunResponse must expose test_case_id for direct traceability (ISTQB §5.3)."""
    assert "test_case_id" in TestRunResponse.model_fields


def test_test_run_response_serializes():
    """TestRunResponse serializes correctly with minimal fields."""
    run = TestRunResponse(
        id="run-1",
        base_url="http://localhost:3000",
        browser="chromium",
        viewport="1920x1080",
        timeout_ms=30000,
        headless=True,
        record_video=False,
        capture_screenshots_on_failure=True,
        status="completed",
        started_at=datetime.now(),
    )
    assert run.test_case_id is None
    assert run.result is None
    assert run.steps == []


def test_test_run_with_result():
    """TestRunResponse correctly nests TestResultResponse."""
    result = TestResultResponse(
        id="res-1",
        status="passed",
        justification="All assertions passed",
        duration=2.3,
        step_count=5,
    )
    run = TestRunResponse(
        id="run-1",
        test_case_id="tc-1",
        base_url="http://localhost:3000",
        browser="chromium",
        viewport="1920x1080",
        timeout_ms=30000,
        headless=True,
        record_video=False,
        capture_screenshots_on_failure=True,
        status="completed",
        started_at=datetime.now(),
        result=result,
    )
    assert run.result.status == "passed"
    assert run.test_case_id == "tc-1"
