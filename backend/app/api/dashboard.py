"""Dashboard statistics endpoint — data scoped to the current user's projects."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.jira_connection import JiraConnection
from app.models.jira_project import JiraProject
from app.models.test_case import TestCase
from app.models.test_suite import TestSuite  
from app.models.test_plan import TestPlan      
from app.models.user import User
from app.models.user_story import UserStory

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ── Response schemas ───────────────────────────────────────────────────────────

class CoverageItem(BaseModel):
    label: str
    value: float   # percentage 0-100


class PriorityItem(BaseModel):
    label: str
    value: int
    color_class: str  # "red" | "orange" | "teal" | "gray"


class ActivityItem(BaseModel):
    message: str
    time: str
    kind: str  # "test_case" | "user_story"


class DashboardStatsResponse(BaseModel):
    user_stories_count: int
    user_stories_this_week: int
    test_cases_count: int
    test_cases_this_week: int
    gherkin_coverage: float
    quality_score: float
    scored_stories_count: int   # stories that have been through AI refinement
    projects_count: int
    has_data: bool
    test_type_coverage: List[CoverageItem]
    priority_distribution: List[PriorityItem]
    recent_activities: List[ActivityItem]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _time_ago(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    minutes = int(diff.total_seconds() / 60)
    hours   = minutes // 60
    days    = hours // 24
    if minutes < 2:  return "Just now"
    if minutes < 60: return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    if hours   < 24: return f"{hours} hour{'s' if hours > 1 else ''} ago"
    if days    == 1: return "Yesterday"
    if days    <  7: return f"{days} days ago"
    return dt.strftime("%d/%m/%Y")


_TYPE_LABELS = {
    "positive":       "Positive",
    "negative":       "Negative",
    "boundary-value": "Boundary Values",
    "edge-case":      "Edge Cases",
    "smoke":          "Smoke",
    "regression":     "Regression",
}

_PRIO_META = {
    "critical": ("Critical", "red"),
    "high":     ("High",     "orange"),
    "medium":   ("Medium",   "teal"),
    "low":      ("Low",      "gray"),
}


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return dashboard statistics scoped to the current user's Jira projects."""
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # ── 1. User's project IDs ──────────────────────────────────────────────────
    proj_r = await db.execute(
        select(JiraProject.id)
        .join(JiraConnection, JiraProject.jira_connection_id == JiraConnection.id)
        .where(JiraConnection.user_id == current_user.id)
    )
    project_ids = [r[0] for r in proj_r.fetchall()]

    if not project_ids:
        return DashboardStatsResponse(
            user_stories_count=0, user_stories_this_week=0,
            test_cases_count=0, test_cases_this_week=0,
            gherkin_coverage=0.0, quality_score=0.0,
            scored_stories_count=0, projects_count=0, has_data=False,
            test_type_coverage=[], priority_distribution=[],
            recent_activities=[],
        )

    # ── 2. User story stats ────────────────────────────────────────────────────
    us_agg = await db.execute(
        select(
            func.count(UserStory.id),
            func.avg(UserStory.current_score),
            func.count(UserStory.current_score),  # counts non-NULL rows only
        )
        .where(UserStory.project_id.in_(project_ids))
    )
    us_total, avg_score_raw, scored_count = us_agg.fetchone()
    us_total = us_total or 0
    scored_count = int(scored_count or 0)
    avg_score_raw = float(avg_score_raw or 0)
    quality_score = round(avg_score_raw * 100 if avg_score_raw <= 1.0 else avg_score_raw, 1)

    us_week = await db.execute(
        select(func.count(UserStory.id))
        .where(UserStory.project_id.in_(project_ids), UserStory.created_at >= one_week_ago)
    )
    us_this_week = us_week.scalar() or 0

    # ── 3. Test case stats (via TestSuite → TestPlan) ──────────────────────────
    base_tc = (
        select(TestCase.id)
        .join(TestSuite, TestCase.test_suite_id == TestSuite.id)      
        .join(TestPlan, TestSuite.test_plan_id == TestPlan.id)        
        .where(TestPlan.project_id.in_(project_ids), TestCase.is_active == True)
        .subquery()
    )

    tc_total_r = await db.execute(select(func.count()).select_from(base_tc))
    tc_total = tc_total_r.scalar() or 0

    tc_week_r = await db.execute(
        select(func.count(TestCase.id))
        .join(TestSuite, TestCase.test_suite_id == TestSuite.id)      
        .join(TestPlan, TestSuite.test_plan_id == TestPlan.id)        
        .where(
            TestPlan.project_id.in_(project_ids),
            TestCase.is_active == True,
            TestCase.created_at >= one_week_ago,
        )
    )
    tc_this_week = tc_week_r.scalar() or 0

    tc_gherkin_r = await db.execute(
        select(func.count(TestCase.id))
        .join(TestSuite, TestCase.test_suite_id == TestSuite.id)      
        .join(TestPlan, TestSuite.test_plan_id == TestPlan.id)        
        .where(
            TestPlan.project_id.in_(project_ids),
            TestCase.is_active == True,
            TestCase.gherkin_source.isnot(None),
            TestCase.gherkin_source != "",
        )
    )
    tc_with_gherkin = tc_gherkin_r.scalar() or 0
    gherkin_coverage = round(tc_with_gherkin / tc_total * 100, 1) if tc_total else 0.0

    # ── 4. Test type coverage ──────────────────────────────────────────────────
    # Query test cases via user_story path first (AI-generated TCs).
    # Fall back to test_suite path if needed.
    type_r = await db.execute(
        select(TestCase.test_type, func.count(TestCase.id).label("cnt"))
        .join(UserStory, TestCase.user_story_id == UserStory.id)
        .where(UserStory.project_id.in_(project_ids), TestCase.is_active == True)
        .group_by(TestCase.test_type)
    )
    type_rows = type_r.fetchall()

    if not type_rows:
        type_r2 = await db.execute(
            select(TestCase.test_type, func.count(TestCase.id).label("cnt"))
            .join(TestSuite, TestCase.test_suite_id == TestSuite.id)
            .join(TestPlan, TestSuite.test_plan_id == TestPlan.id)
            .where(TestPlan.project_id.in_(project_ids), TestCase.is_active == True)
            .group_by(TestCase.test_type)
        )
        type_rows = type_r2.fetchall()

    type_counts: dict[str, int] = {k: 0 for k in _TYPE_LABELS}
    type_total = 0
    for row in type_rows:
        key = (row.test_type or "").lower().replace(" ", "-")
        if key in type_counts:
            type_counts[key] = row.cnt
        type_total += row.cnt

    denom = type_total or tc_total or 1

    test_type_coverage = [
        CoverageItem(
            label=_TYPE_LABELS[t],
            value=round(cnt / denom * 100, 1),
        )
        for t, cnt in type_counts.items()
        if cnt > 0
    ]
    if not test_type_coverage:
        test_type_coverage = [
            CoverageItem(label=lbl, value=0.0) for lbl in _TYPE_LABELS.values()
        ]

    # ── 5. Priority distribution ───────────────────────────────────────────────
    prio_r = await db.execute(
        select(TestCase.risk_level, func.count(TestCase.id).label("cnt"))
        .join(TestSuite, TestCase.test_suite_id == TestSuite.id)      
        .join(TestPlan, TestSuite.test_plan_id == TestPlan.id)        
        .where(TestPlan.project_id.in_(project_ids), TestCase.is_active == True)
        .group_by(TestCase.risk_level)
        .order_by(func.count(TestCase.id).desc())
    )
    priority_distribution = [
        PriorityItem(
            label=_PRIO_META.get(row.risk_level or "", ("Other", "gray"))[0],
            value=row.cnt,
            color_class=_PRIO_META.get(row.risk_level or "", ("Other", "gray"))[1],
        )
        for row in prio_r.fetchall()
    ]

    # ── 6. Recent activity feed ────────────────────────────────────────────────
    tc_feed_r = await db.execute(
        select(TestCase.title, TestCase.created_at)
        .join(TestSuite, TestCase.test_suite_id == TestSuite.id)      
        .join(TestPlan, TestSuite.test_plan_id == TestPlan.id)        
        .where(TestPlan.project_id.in_(project_ids), TestCase.is_active == True)
        .order_by(TestCase.created_at.desc())
        .limit(5)
    )
    us_feed_r = await db.execute(
        select(UserStory.issue_key, UserStory.title, UserStory.created_at)
        .where(UserStory.project_id.in_(project_ids))
        .order_by(UserStory.created_at.desc())
        .limit(4)
    )

    feed: list[dict] = []
    for row in tc_feed_r.fetchall():
        feed.append({
            "message": f"Test case generated: {(row.title or '')[:55]}",
            "dt": row.created_at,
            "kind": "test_case",
        })
    for row in us_feed_r.fetchall():
        feed.append({
            "message": f"User story imported: {row.issue_key} – {(row.title or '')[:40]}",
            "dt": row.created_at,
            "kind": "user_story",
        })

    def _sort_key(a: dict) -> datetime:
        dt = a["dt"]
        if dt is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

    feed.sort(key=_sort_key, reverse=True)
    recent_activities = [
        ActivityItem(message=a["message"], time=_time_ago(a["dt"]), kind=a["kind"])
        for a in feed[:7]
    ]

    return DashboardStatsResponse(
        user_stories_count=us_total,
        user_stories_this_week=us_this_week,
        test_cases_count=tc_total,
        test_cases_this_week=tc_this_week,
        gherkin_coverage=gherkin_coverage,
        quality_score=quality_score,
        scored_stories_count=scored_count,
        projects_count=len(project_ids),
        has_data=True,
        test_type_coverage=test_type_coverage,
        priority_distribution=priority_distribution,
        recent_activities=recent_activities,
    )