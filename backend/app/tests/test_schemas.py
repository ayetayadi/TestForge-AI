"""
Schema validation tests — verifies Pydantic schemas match model fields
and expose the required ISTQB traceability fields.
"""

import pytest
from datetime import datetime
from app.schemas.test_case_schema import TestCaseResponse
from app.schemas.tc_coverage_schema import TcCoverageResponse, TcCoverageSummary
from app.schemas.test_execution_schema import TestCaseResultDetail, TestExecutionBasic


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


# ─── TestExecution / TestCaseResult schemas ──────────────────────────────────

def test_tc_result_detail_has_traceability_fields():
    """TestCaseResultDetail must expose test_case_id for traceability (ISTQB §5.3)."""
    assert "test_case_id" in TestCaseResultDetail.model_fields
    assert "execution_order" in TestCaseResultDetail.model_fields
    assert "steps" in TestCaseResultDetail.model_fields


def test_tc_result_detail_serializes():
    """TestCaseResultDetail serializes with minimal fields."""
    r = TestCaseResultDetail(
        id="tcr-1",
        test_case_id="tc-1",
        execution_order=1,
        status="passed",
    )
    assert r.status == "passed"
    assert r.steps == []
    assert r.screenshot_b64 is None


def test_test_execution_basic_serializes():
    """TestExecutionBasic exposes suite-level counters."""
    ex = TestExecutionBasic(
        id="ex-1",
        suite_id="suite-1",
        app_url="http://localhost:3010",
        browser="chromium",
        headless=True,
        status="completed",
        started_at=datetime.now(),
        total_count=3,
        passed_count=2,
        failed_count=1,
    )
    assert ex.total_count == 3
    assert ex.passed_count == 2
    assert ex.failed_count == 1
