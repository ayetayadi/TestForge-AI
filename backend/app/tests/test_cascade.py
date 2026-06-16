"""
Cascade deletion tests — ISTQB §1.4 (traceability) and §5.2 (test plan integrity).

These tests verify that deleting a parent entity produces the expected
cascade / SET NULL / passive_deletes behaviour at the ORM level.
"""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    UserStory, UserStoryVersion, Risk, Defect,
    TestPlan, TestSuite, TestCase, TcCoverage,
)


# ─── UserStory cascade ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_user_story_cascades_versions(db: AsyncSession, user_story: UserStory):
    """Deleting a UserStory must delete all its UserStoryVersions."""
    version = UserStoryVersion(
        id="v-1",
        user_story_id=user_story.id,
        version_number=1,
        workflow_status="completed",
        decision_status="pending",
    )
    db.add(version)
    await db.commit()

    await db.delete(user_story)
    await db.commit()

    result = await db.execute(select(UserStoryVersion).where(UserStoryVersion.id == "v-1"))
    assert result.scalar_one_or_none() is None, "UserStoryVersion must be deleted with its parent"


@pytest.mark.asyncio
async def test_delete_user_story_nullifies_test_case(db: AsyncSession, test_case: TestCase, user_story: UserStory):
    """Deleting a UserStory must SET NULL on TestCase.user_story_id (preserve the test case)."""
    await db.delete(user_story)
    await db.commit()

    await db.refresh(test_case)
    assert test_case.user_story_id is None, "TestCase must survive with user_story_id=NULL"
    assert test_case.id == "tc-1", "TestCase must not be deleted"


@pytest.mark.asyncio
async def test_delete_user_story_passive_deletes_risk(db: AsyncSession, user_story: UserStory):
    """Risk with nullable=False user_story_id must not raise IntegrityError on story delete."""
    risk = Risk(
        id="risk-1",
        user_story_id=user_story.id,
        probability=4,
        impact=5,
        risk_score=20,
        level="critical",
        description="Payment failure under load",
        test_depth="comprehensive",
        source="original",
    )
    db.add(risk)
    await db.commit()

    # Should NOT raise IntegrityError thanks to passive_deletes=True
    await db.delete(user_story)
    await db.commit()

    result = await db.execute(select(Risk).where(Risk.id == "risk-1"))
    assert result.scalar_one_or_none() is None, "Risk must be cascade-deleted with its UserStory"


# ─── TestPlan cascade ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_test_plan_cascades_test_cases(db: AsyncSession, test_plan: TestPlan, test_case: TestCase):
    """Deleting a TestPlan must delete all its TestCases (ISTQB §5.2 — plan owns its cases)."""
    await db.delete(test_plan)
    await db.commit()

    result = await db.execute(select(TestCase).where(TestCase.id == "tc-1"))
    assert result.scalar_one_or_none() is None, "TestCase must be cascade-deleted with its TestPlan"


@pytest.mark.asyncio
async def test_delete_test_plan_cascades_tc_coverage(db: AsyncSession, test_plan: TestPlan, user_story: UserStory):
    """Deleting a TestPlan must delete all its TcCoverage rows."""
    cov = TcCoverage(
        id="cov-1",
        test_plan_id=test_plan.id,
        user_story_id=user_story.id,
        issue_key="TF-1",
        user_story_title="As a user I can log in",
        scenario_type="positive",
        coverage_pct=0.75,
        covered_count=3,
        total_ac_count=4,
        tc_count=3,
    )
    db.add(cov)
    await db.commit()

    await db.delete(test_plan)
    await db.commit()

    result = await db.execute(select(TcCoverage).where(TcCoverage.id == "cov-1"))
    assert result.scalar_one_or_none() is None, "TcCoverage must be cascade-deleted with its TestPlan"


# ─── TestCase cascade ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_test_case_preserves_defect_with_null(db: AsyncSession, test_case: TestCase, user_story: UserStory):
    """Deleting a TestCase must SET NULL on Defect.test_case_id (ISTQB §6.5 — defect history)."""
    defect = Defect(
        id="def-1",
        test_case_id=test_case.id,
        title="Login button not clickable",
        severity="high",
        status="open",
    )
    db.add(defect)
    await db.commit()

    await db.delete(test_case)
    await db.commit()

    await db.refresh(defect)
    assert defect.test_case_id is None, "Defect must survive with test_case_id=NULL"
