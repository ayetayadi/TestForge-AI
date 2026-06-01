"""Dashboard statistics endpoint — scoped to the current user's projects."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.jira_connection import JiraConnection
from app.models.jira_project import JiraProject
from app.models.risk import Risk
from app.models.test_case import TestCase
from app.models.test_execution import TestExecution
from app.models.test_plan import TestPlan
from app.models.test_suite import TestSuite
from app.models.user import User
from app.models.user_story import UserStory

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ── Response schemas ───────────────────────────────────────────────────────────

class ProjectRow(BaseModel):
    project_id: str
    project_key: str
    project_name: str
    stories_count: int
    refined_count: int       # US that went through AI refinement (current_score IS NOT NULL)
    risks_count: int         # risks analyzed for this project's US
    test_plans_count: int
    test_suites_count: int
    test_cases_count: int
    executions_count: int
    passed_count: int
    failed_count: int


class DashboardStatsResponse(BaseModel):
    # Global totals
    projects_count: int
    stories_count: int
    refined_count: int
    risks_count: int
    test_plans_count: int
    test_suites_count: int
    test_cases_count: int
    executions_count: int
    passed_count: int
    failed_count: int
    has_data: bool
    # Per-project breakdown
    projects: List[ProjectRow]


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return enriched dashboard statistics scoped to the current user's projects."""

    # ── 1. Resolve user's project IDs ─────────────────────────────────────────
    proj_r = await db.execute(
        select(JiraProject.id, JiraProject.project_key, JiraProject.project_name)
        .join(JiraConnection, JiraProject.jira_connection_id == JiraConnection.id)
        .where(JiraConnection.user_id == current_user.id)
        .order_by(JiraProject.project_name)
    )
    project_rows = proj_r.fetchall()
    project_ids = [r.id for r in project_rows]

    if not project_ids:
        return DashboardStatsResponse(
            projects_count=0, stories_count=0, refined_count=0,
            risks_count=0, test_plans_count=0, test_suites_count=0,
            test_cases_count=0, executions_count=0,
            passed_count=0, failed_count=0,
            has_data=False, projects=[],
        )

    # ── 2. User stories per project ───────────────────────────────────────────
    us_r = await db.execute(
        select(
            UserStory.project_id,
            func.count(UserStory.id).label("stories"),
            func.count(UserStory.current_score).label("refined"),  # counts non-NULL only
        )
        .where(UserStory.project_id.in_(project_ids))
        .group_by(UserStory.project_id)
    )
    us_by_proj: dict[str, tuple[int, int]] = {
        r.project_id: (r.stories, r.refined) for r in us_r.fetchall()
    }

    # ── 3. Risks per project ──────────────────────────────────────────────────
    risk_r = await db.execute(
        select(UserStory.project_id, func.count(Risk.id).label("cnt"))
        .join(Risk, Risk.user_story_id == UserStory.id)
        .where(UserStory.project_id.in_(project_ids))
        .group_by(UserStory.project_id)
    )
    risks_by_proj: dict[str, int] = {r.project_id: r.cnt for r in risk_r.fetchall()}

    # ── 4. Test plans per project ─────────────────────────────────────────────
    tp_r = await db.execute(
        select(TestPlan.project_id, func.count(TestPlan.id).label("cnt"))
        .where(TestPlan.project_id.in_(project_ids))
        .group_by(TestPlan.project_id)
    )
    plans_by_proj: dict[str, int] = {r.project_id: r.cnt for r in tp_r.fetchall()}

    # ── 5. Test suites per project (via test plan) ────────────────────────────
    ts_r = await db.execute(
        select(TestPlan.project_id, func.count(TestSuite.id).label("cnt"))
        .join(TestSuite, TestSuite.test_plan_id == TestPlan.id)
        .where(TestPlan.project_id.in_(project_ids))
        .group_by(TestPlan.project_id)
    )
    suites_by_proj: dict[str, int] = {r.project_id: r.cnt for r in ts_r.fetchall()}

    # ── 6. Test cases per project (via suite → plan) ──────────────────────────
    tc_r = await db.execute(
        select(TestPlan.project_id, func.count(TestCase.id).label("cnt"))
        .join(TestSuite, TestSuite.test_plan_id == TestPlan.id)
        .join(TestCase, TestCase.test_suite_id == TestSuite.id)
        .where(TestPlan.project_id.in_(project_ids), TestCase.is_active == True)
        .group_by(TestPlan.project_id)
    )
    tc_by_proj: dict[str, int] = {r.project_id: r.cnt for r in tc_r.fetchall()}

    # ── 7. Executions per project (count + passed + failed) ───────────────────
    exec_r = await db.execute(
        select(
            TestPlan.project_id,
            func.count(TestExecution.id).label("exec_cnt"),
            func.coalesce(func.sum(TestExecution.passed_count), 0).label("passed"),
            func.coalesce(func.sum(TestExecution.failed_count), 0).label("failed"),
        )
        .join(TestSuite, TestSuite.test_plan_id == TestPlan.id)
        .join(TestExecution, TestExecution.suite_id == TestSuite.id)
        .where(TestPlan.project_id.in_(project_ids))
        .group_by(TestPlan.project_id)
    )
    exec_by_proj: dict[str, tuple[int, int, int]] = {
        r.project_id: (r.exec_cnt, int(r.passed), int(r.failed))
        for r in exec_r.fetchall()
    }

    # ── 8. Build per-project rows ─────────────────────────────────────────────
    projects: list[ProjectRow] = []
    for proj in project_rows:
        pid = proj.id
        stories, refined = us_by_proj.get(pid, (0, 0))
        exec_cnt, passed, failed = exec_by_proj.get(pid, (0, 0, 0))
        projects.append(ProjectRow(
            project_id=pid,
            project_key=proj.project_key,
            project_name=proj.project_name,
            stories_count=stories,
            refined_count=refined,
            risks_count=risks_by_proj.get(pid, 0),
            test_plans_count=plans_by_proj.get(pid, 0),
            test_suites_count=suites_by_proj.get(pid, 0),
            test_cases_count=tc_by_proj.get(pid, 0),
            executions_count=exec_cnt,
            passed_count=passed,
            failed_count=failed,
        ))

    # ── 9. Global totals ──────────────────────────────────────────────────────
    def _sum(d: dict, key=None) -> int:
        if key is None:
            return sum(d.values())
        return sum(v[key] for v in d.values())

    global_stories  = sum(v[0] for v in us_by_proj.values())
    global_refined  = sum(v[1] for v in us_by_proj.values())
    global_risks    = sum(risks_by_proj.values())
    global_plans    = sum(plans_by_proj.values())
    global_suites   = sum(suites_by_proj.values())
    global_tc       = sum(tc_by_proj.values())
    global_execs    = sum(v[0] for v in exec_by_proj.values())
    global_passed   = sum(v[1] for v in exec_by_proj.values())
    global_failed   = sum(v[2] for v in exec_by_proj.values())

    return DashboardStatsResponse(
        projects_count=len(project_ids),
        stories_count=global_stories,
        refined_count=global_refined,
        risks_count=global_risks,
        test_plans_count=global_plans,
        test_suites_count=global_suites,
        test_cases_count=global_tc,
        executions_count=global_execs,
        passed_count=global_passed,
        failed_count=global_failed,
        has_data=True,
        projects=projects,
    )
