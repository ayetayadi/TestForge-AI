"""
Tasty query tools — read-only DB access for projects, stories, test cases, and stats.
Each factory function closes over the authenticated user_id.
"""
from __future__ import annotations

import logging
from typing import List

from langchain_core.tools import tool
from sqlalchemy import func, select

from app.core.database import async_session_maker
from app.models.jira_connection import JiraConnection
from app.models.jira_project import JiraProject
from app.models.playwright_script_version import PlaywrightScriptVersion
from app.models.test_case import TestCase
from app.models.test_plan import TestPlan
from app.models.test_case_result import TestCaseResult
from app.models.test_suite import TestSuite
from app.models.user_story import UserStory

logger = logging.getLogger(__name__)


def make_query_tools(user_id: str) -> List:
    """Return read-only query tools bound to the given user_id."""

    @tool("get_projects")
    async def get_projects() -> str:
        """Get all Jira projects available to the current user."""
        async with async_session_maker() as db:
            result = await db.execute(
                select(JiraProject)
                .join(JiraConnection, JiraConnection.id == JiraProject.jira_connection_id)
                .where(JiraConnection.user_id == user_id)
                .order_by(JiraProject.project_name)
            )
            projects = result.scalars().all()

        if not projects:
            return (
                "No projects found. Make sure you have connected a Jira account "
                "and imported at least one project."
            )

        rows = [
            f"- **{p.project_name}** (`{p.project_key}`) — ID: `{p.id}`"
            for p in projects
        ]
        return f"## Your Projects ({len(projects)} total)\n\n" + "\n".join(rows)

    @tool("get_user_stories")
    async def get_user_stories(project_id: str) -> str:
        """
        Get user stories for a specific project.

        Args:
            project_id: The project UUID (from get_projects)
        """
        async with async_session_maker() as db:
            # Verify the project belongs to this user
            proj_result = await db.execute(
                select(JiraProject)
                .join(JiraConnection, JiraConnection.id == JiraProject.jira_connection_id)
                .where(JiraProject.id == project_id, JiraConnection.user_id == user_id)
            )
            project = proj_result.scalar_one_or_none()
            if not project:
                return f"Project `{project_id}` not found or you don't have access to it."

            result = await db.execute(
                select(UserStory)
                .where(UserStory.project_id == project_id)
                .order_by(UserStory.issue_key)
                .limit(25)
            )
            stories = result.scalars().all()

        if not stories:
            return (
                f"No user stories found in project **{project.project_name}**. "
                "Try syncing your Jira project first."
            )

        rows = []
        for s in stories:
            ac_count = len(s.acceptance_criteria or [])
            score = f"{round(s.current_score * 100)}%" if s.current_score is not None else "—"
            rows.append(
                f"- **{s.issue_key}**: {s.title[:75]} "
                f"| ACs: {ac_count} | Status: {s.jira_status or 'N/A'} "
                f"| Score: {score} | ID: `{s.id}`"
            )

        return (
            f"## User Stories in **{project.project_name}** ({len(stories)} shown)\n\n"
            + "\n".join(rows)
        )

    @tool("get_test_cases")
    async def get_test_cases(user_story_id: str) -> str:
        """
        Get all test cases for a specific user story.

        Args:
            user_story_id: The user story UUID (from get_user_stories)
        """
        async with async_session_maker() as db:
            story = await db.get(UserStory, user_story_id)
            result = await db.execute(
                select(TestCase)
                .where(
                    TestCase.user_story_id == user_story_id,
                    TestCase.is_active == True,
                )
                .order_by(TestCase.tc_code)
            )
            test_cases = result.scalars().all()

        story_label = (
            f"**{story.issue_key}: {story.title[:60]}**" if story else f"`{user_story_id}`"
        )

        if not test_cases:
            return (
                f"No test cases found for {story_label}. "
                "You can generate them by asking me to generate test cases for this story."
            )

        rows = []
        for tc in test_cases:
            step_count = len(tc.steps or [])
            tags = ", ".join(tc.tags or []) or "—"
            rows.append(
                f"- **{tc.tc_code}** [{tc.priority or 'Medium'}]: {tc.title[:70]} "
                f"| Steps: {step_count} | Tags: {tags}"
            )

        return (
            f"## Test Cases for {story_label} ({len(test_cases)} total)\n\n"
            + "\n".join(rows)
        )

    @tool("get_test_stats")
    async def get_test_stats() -> str:
        """Get overall testing statistics and coverage for the current user."""
        async with async_session_maker() as db:
            proj_count = (
                await db.execute(
                    select(func.count(JiraProject.id))
                    .join(JiraConnection, JiraConnection.id == JiraProject.jira_connection_id)
                    .where(JiraConnection.user_id == user_id)
                )
            ).scalar() or 0

            story_count = (
                await db.execute(
                    select(func.count(UserStory.id))
                    .join(JiraProject, JiraProject.id == UserStory.project_id)
                    .join(JiraConnection, JiraConnection.id == JiraProject.jira_connection_id)
                    .where(JiraConnection.user_id == user_id)
                )
            ).scalar() or 0

            tc_count = (
                await db.execute(
                    select(func.count(TestCase.id))
                    .join(UserStory, UserStory.id == TestCase.user_story_id)
                    .join(JiraProject, JiraProject.id == UserStory.project_id)
                    .join(JiraConnection, JiraConnection.id == JiraProject.jira_connection_id)
                    .where(
                        JiraConnection.user_id == user_id,
                        TestCase.is_active == True,
                    )
                )
            ).scalar() or 0

            # Stories that have at least one test case
            covered_stories = (
                await db.execute(
                    select(func.count(func.distinct(TestCase.user_story_id)))
                    .join(UserStory, UserStory.id == TestCase.user_story_id)
                    .join(JiraProject, JiraProject.id == UserStory.project_id)
                    .join(JiraConnection, JiraConnection.id == JiraProject.jira_connection_id)
                    .where(
                        JiraConnection.user_id == user_id,
                        TestCase.is_active == True,
                    )
                )
            ).scalar() or 0

        coverage = round(covered_stories / story_count * 100, 1) if story_count > 0 else 0.0
        avg_tc = round(tc_count / covered_stories, 1) if covered_stories > 0 else 0.0

        return (
            "## TestForge AI — Your Stats\n\n"
            "| Metric | Value |\n"
            "|--------|-------|\n"
            f"| Projects | {proj_count} |\n"
            f"| User Stories | {story_count} |\n"
            f"| Test Cases | {tc_count} |\n"
            f"| Stories with tests | {covered_stories} / {story_count} |\n"
            f"| Story Coverage | **{coverage}%** |\n"
            f"| Avg. tests per story | {avg_tc} |\n"
        )

    @tool("search_test_cases")
    async def search_test_cases(query: str) -> str:
        """
        Search test cases by title keyword or tc_code (e.g. "TC-PROJ-001") across all projects.

        Args:
            query: Keyword or tc_code to search for
        """
        async with async_session_maker() as db:
            result = await db.execute(
                select(TestCase)
                .join(UserStory, UserStory.id == TestCase.user_story_id)
                .join(JiraProject, JiraProject.id == UserStory.project_id)
                .join(JiraConnection, JiraConnection.id == JiraProject.jira_connection_id)
                .where(
                    JiraConnection.user_id == user_id,
                    TestCase.is_active == True,
                    (TestCase.title.ilike(f"%{query}%") | TestCase.tc_code.ilike(f"%{query}%")),
                )
                .order_by(TestCase.tc_code)
                .limit(15)
            )
            results = result.scalars().all()

        if not results:
            return f"No test cases found matching **\"{query}\"**."

        rows = [
            f"- **{tc.tc_code}** (ID: `{tc.id}`): {tc.title[:80]}"
            for tc in results
        ]
        return (
            f"## Search Results for \"{query}\" ({len(results)} found)\n\n"
            + "\n".join(rows)
        )

    @tool("get_test_suites")
    async def get_test_suites(project_id: str) -> str:
        """
        List all test suites in a project, with their TC count, status, and
        Playwright execution readiness.

        Args:
            project_id: The project UUID (from get_projects)
        """
        async with async_session_maker() as db:
            proj_result = await db.execute(
                select(JiraProject)
                .join(JiraConnection, JiraConnection.id == JiraProject.jira_connection_id)
                .where(JiraProject.id == project_id, JiraConnection.user_id == user_id)
            )
            project = proj_result.scalar_one_or_none()
            if not project:
                return f"Project `{project_id}` not found or you don't have access to it."

            plans_r = await db.execute(
                select(TestPlan.id).where(TestPlan.project_id == project_id)
            )
            plan_ids = [r[0] for r in plans_r.fetchall()]
            if not plan_ids:
                return (
                    f"No test plans found in **{project.project_name}**. "
                    "Create a test plan first to organise your suites."
                )

            suites_r = await db.execute(
                select(TestSuite)
                .where(TestSuite.test_plan_id.in_(plan_ids))
                .order_by(TestSuite.execution_order.asc().nullslast(), TestSuite.title)
            )
            suites = suites_r.scalars().all()

            if not suites:
                return f"No test suites found in **{project.project_name}**."

            # Batch TC counts
            tc_counts_r = await db.execute(
                select(TestCase.test_suite_id, func.count(TestCase.id).label("cnt"))
                .where(
                    TestCase.test_suite_id.in_([s.id for s in suites]),
                    TestCase.is_active == True,
                )
                .group_by(TestCase.test_suite_id)
            )
            tc_map = {row.test_suite_id: row.cnt for row in tc_counts_r.fetchall()}

        rows = []
        for s in suites:
            tc_cnt = tc_map.get(s.id, 0)
            rows.append(
                f"- **{s.title}** | {tc_cnt} TCs | Status: `{s.status}` | "
                f"Priority: {s.priority or '—'} | ID: `{s.id}`"
            )

        return (
            f"## Test Suites in **{project.project_name}** ({len(suites)} suites)\n\n"
            + "\n".join(rows)
            + "\n\nTip: use `get_suite_results(suite_id)` to see the latest execution results, "
            "or ask me to run a suite."
        )

    @tool("get_suite_results")
    async def get_suite_results(suite_id: str) -> str:
        """
        Get the latest Playwright execution results for every test case in a suite.

        Args:
            suite_id: The test suite UUID (from get_test_suites)
        """
        async with async_session_maker() as db:
            suite = await db.get(TestSuite, suite_id)
            if not suite:
                return f"Test suite `{suite_id}` not found."

            tcs_r = await db.execute(
                select(TestCase)
                .where(TestCase.test_suite_id == suite_id, TestCase.is_active == True)
                .order_by(TestCase.execution_order.asc().nullslast(), TestCase.tc_code)
            )
            tcs = tcs_r.scalars().all()

        if not tcs:
            return f"Suite **{suite.title}** has no active test cases."

        rows = []
        passed = failed = pending = 0
        async with async_session_maker() as db:
            for tc in tcs:
                # Latest TestCaseResult for this TC (all executions)
                tcr_r = await db.execute(
                    select(TestCaseResult)
                    .where(TestCaseResult.test_case_id == tc.id)
                    .order_by(TestCaseResult.created_at.desc())
                    .limit(1)
                )
                tc_result = tcr_r.scalar_one_or_none()

                if tc_result is None:
                    status_icon = "⏳"
                    status_text = "not run"
                    pending += 1
                else:
                    result_status = tc_result.status.value
                    if result_status == "passed":
                        status_icon, status_text = "✅", "passed"
                        passed += 1
                    elif result_status == "error":
                        status_icon, status_text = "💥", "error"
                        failed += 1
                    else:
                        status_icon, status_text = "❌", "failed"
                        failed += 1

                    duration = (
                        f" ({round(tc_result.duration or 0, 1)} s)"
                        if tc_result.duration else ""
                    )
                    rows.append(
                        f"- {status_icon} **{tc.tc_code}**: {tc.title[:65]} "
                        f"— `{status_text}`{duration}"
                    )
                    continue

                rows.append(
                    f"- {status_icon} **{tc.tc_code}**: {tc.title[:65]} — `{status_text}`"
                )

        total = len(tcs)
        summary = (
            f"**{passed}/{total} passed** | {failed} failed | {pending} not run yet"
        )
        return (
            f"## Execution Results — {suite.title}\n\n"
            f"{summary}\n\n"
            + "\n".join(rows)
        )

    return [get_projects, get_user_stories, get_test_cases, get_test_stats,
            search_test_cases, get_test_suites, get_suite_results]
