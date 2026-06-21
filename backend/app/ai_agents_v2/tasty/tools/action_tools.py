"""
Tasty action tools — call the exact same service functions the UI buttons use,
so every action Tasty takes is reflected live in the application.
"""
from __future__ import annotations

import logging
import re
from typing import List

from langchain_core.tools import tool
from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.test_case import TestCase
from app.models.user_story import UserStory

logger = logging.getLogger(__name__)


def _extract_module(issue_key: str) -> str:
    match = re.match(r"^([A-Z0-9]+)-", issue_key.upper())
    return match.group(1) if match else re.sub(r"[^A-Z]", "", issue_key.upper()) or "GEN"


async def _next_tc_codes(db, module: str, count: int) -> List[str]:
    prefix = f"TC-{module}-"
    result = await db.execute(
        select(TestCase.tc_code).where(TestCase.tc_code.like(f"{prefix}%"))
    )
    existing = [
        int(m.group(1))
        for (code,) in result.fetchall()
        if (m := re.search(r"-(\d+)$", code))
    ]
    start = max(existing, default=0) + 1
    return [f"{prefix}{start + i:03d}" for i in range(count)]


def make_action_tools(user_id: str) -> List:
    """
    Return action tools that call the same service functions as the UI.
    This means every action Tasty takes is immediately visible in the app.
    """

    @tool("refine_user_story")
    async def refine_user_story(user_story_id: str) -> str:
        """
        Launch the AI refinement pipeline for a user story — exactly like clicking
        the 'Refine' button in the app. The new version will appear in the
        Versions page when it completes (usually within 30–60 seconds).

        Args:
            user_story_id: The UUID of the user story to refine
        """
        from app.services.user_story_version_service import start_version
        from app.workers.us_worker import submit_version

        async with async_session_maker() as db:
            story: UserStory | None = await db.get(UserStory, user_story_id)
            if not story:
                return f"User story `{user_story_id}` not found."

            issue_key = story.issue_key
            title = story.title

            try:
                version_id, state = await start_version(db, story)
                await db.commit()
            except ValueError as exc:
                return f"Cannot start refinement for **{issue_key}**: {exc}"
            except Exception as exc:
                logger.exception("[Tasty] start_version failed: %s", exc)
                return f"Failed to initialize refinement pipeline: {exc}"

        # Submit to the worker queue — same path as the UI
        try:
            await submit_version(state)
        except Exception as exc:
            logger.exception("[Tasty] submit_version failed: %s", exc)
            return f"Failed to queue refinement job: {exc}"

        logger.info("[Tasty] Refinement queued for story=%s version=%s", issue_key, version_id)

        return (
            f"## Refinement Started\n\n"
            f"The AI refinement pipeline has been launched for "
            f"**{issue_key}: {title[:60]}**.\n\n"
            f"- Version ID: `{version_id}`\n"
            f"- The new version will appear in the **Versions** page once processing completes (30–60 seconds).\n"
            f"- You can open the story and check the Versions tab to track progress."
        )

    @tool("generate_test_cases")
    async def generate_test_cases(user_story_id: str) -> str:
        """
        Generate AI test cases for a user story and save them to the database —
        exactly like clicking the 'Generate Test Cases' button. The generated test
        cases will immediately appear on the Test Cases page.

        Args:
            user_story_id: The UUID of the user story to generate test cases for
        """
        from app.ai_workflows.test_case import get_pipeline
        from app.services import test_case_service

        async with async_session_maker() as db:
            story: UserStory | None = await db.get(UserStory, user_story_id)
            if not story:
                return f"User story `{user_story_id}` not found."

            story_text = f"As a user, {story.description or story.title}"
            acceptance_criteria = [
                str(ac).strip()
                for ac in (story.acceptance_criteria or [])
                if ac and str(ac).strip()
            ]
            issue_key = story.issue_key or "GEN"
            story_title = story.title

        logger.info("[Tasty] Generating test cases for story=%s", issue_key)

        try:
            pipeline = get_pipeline()
            result = await pipeline.run(
                story=story_text,
                acceptance_criteria=acceptance_criteria,
                user_story_id=user_story_id,
                issue_key=issue_key,
            )
        except Exception as exc:
            logger.exception("[Tasty] TestCaseGenerator failed: %s", exc)
            return f"Test case generation failed: {exc}"

        raw_cases = result.get("test_cases") or []
        if not raw_cases:
            return (
                "The AI agent did not generate any test cases. "
                "Try refining the user story first to improve its quality and testability."
            )

        async with async_session_maker() as db:
            module = _extract_module(issue_key)
            tc_codes = await _next_tc_codes(db, module, len(raw_cases))

            created = []
            for i, tc in enumerate(raw_cases):
                tags = list(tc.get("tags") or [])
                test_type = (tc.get("test_type") or "positive").lower().replace(" ", "-")
                if test_type and test_type not in tags:
                    tags.append(test_type)

                raw_steps = tc.get("steps") or []
                steps = [
                    {
                        "order": s.get("step_number", idx + 1),
                        "action": s.get("description", ""),
                        "expected": s.get("expected_result", ""),
                    }
                    for idx, s in enumerate(raw_steps)
                    if isinstance(s, dict)
                ]

                priority_map = {
                    "high": "high", "medium": "medium",
                    "low": "low", "critical": "critical",
                }
                priority = priority_map.get((tc.get("priority") or "medium").lower(), "medium")

                data = {
                    "tc_code": tc_codes[i],
                    "title": tc.get("name") or f"Test Case {i + 1}",
                    "description": tc.get("description") or None,
                    "priority": priority,
                    "tags": tags,
                    "steps": steps,
                    "gherkin_source": tc.get("gherkin_scenario") or None,
                    "test_data": tc.get("test_data") or None,
                    "user_story_id": user_story_id,
                    "preconditions": [],
                    "postconditions": [],
                    "expected_results": [],
                    "is_active": True,
                }
                try:
                    tc_obj = await test_case_service.create_test_case(db, data)
                    created.append(tc_obj)
                except Exception as exc:
                    logger.warning("[Tasty] Skipping tc %s: %s", tc_codes[i], exc)

            await db.commit()

        quality_score = result.get("last_critic_score", 0)
        flagged = result.get("flagged_for_human", False)

        lines = [
            "## Test Cases Generated\n",
            f"Generated **{len(created)} test cases** for **{issue_key}: {story_title[:60]}**\n",
            f"- Quality score: **{quality_score}/100**",
            f"- Flagged for human review: {'⚠️ Yes — check them before using' if flagged else 'No'}",
            f"- They are now visible on the **Test Cases** page for this story.\n",
            "### Generated",
        ]
        for tc in created[:8]:
            lines.append(f"- **{tc.tc_code}** [{tc.priority}]: {tc.title[:70]}")
        if len(created) > 8:
            lines.append(f"- _…and {len(created) - 8} more_")

        return "\n".join(lines)

    @tool("generate_playwright_script")
    async def generate_playwright_script(test_case_id: str) -> str:
        """
        Generate a Playwright automation script for a test case and save it to
        the database — exactly like clicking 'Generate Script' in the app.
        The script will immediately appear on the Playwright Scripts page.

        Args:
            test_case_id: The UUID of the test case to generate a script for
        """
        from app.services.playwright_service import generate_script_v1
        from app.models.test_case import TestCase as TC

        async with async_session_maker() as db:
            tc: TC | None = await db.get(TC, test_case_id)
            if not tc:
                return f"Test case `{test_case_id}` not found."
            tc_title = tc.title
            tc_code = tc.tc_code

            try:
                result = await generate_script_v1(db, test_case_id=test_case_id, save_to_db=True)
            except Exception as exc:
                logger.exception("[Tasty] generate_script_v1 failed: %s", exc)
                return f"Script generation failed for **{tc_code}**: {exc}"

        if result.get("status") != "generated":
            error = result.get("error", "Unknown generation error")
            return f"Script generation failed for **{tc_code}**: {error}"

        script_version_id = result.get("script_version_id", "N/A")
        version_number = result.get("version_number", 1)
        placeholder_count = result.get("placeholder_count", 0)

        return (
            f"## Playwright Script Generated\n\n"
            f"Script created for **{tc_code}: {tc_title[:60]}**\n\n"
            f"- Script version: **v{version_number}**\n"
            f"- Version ID: `{script_version_id}`\n"
            f"- Placeholders requiring real values: **{placeholder_count}**\n"
            f"- The script is now visible on the **Playwright Scripts** page.\n\n"
            + (
                f"⚠️ This script has **{placeholder_count} placeholder(s)** that need real "
                f"values (credentials, URLs, etc.) before it can run."
                if placeholder_count > 0
                else "✅ No placeholders — the script is ready to execute."
            )
        )

    @tool("execute_playwright_script")
    async def execute_playwright_script(
        test_case_id: str,
        app_url: str = "",
    ) -> str:
        """
        Execute the active Playwright script for a test case against the target app.
        Execution runs in the background and streams live progress to the app UI.
        Returns immediately — the user can watch results live on the Playwright page.

        Args:
            test_case_id: The UUID of the test case to execute
            app_url: The base URL of the application under test (e.g. "http://localhost:3000")
        """
        import asyncio
        from app.services.playwright_service import execute_script
        from app.repositories import playwright_repository as repo
        from app.models.test_case import TestCase as TC

        async with async_session_maker() as db:
            tc: TC | None = await db.get(TC, test_case_id)
            if not tc:
                return f"Test case `{test_case_id}` not found."
            tc_code = tc.tc_code
            tc_title = tc.title

            active_script = await repo.get_active_script(db, test_case_id)
            if not active_script:
                return (
                    f"**{tc_code}** has no active Playwright script yet.\n"
                    "Ask me to `generate_playwright_script` for it first."
                )

        async def _run_in_bg():
            async with async_session_maker() as db:
                await execute_script(
                    db,
                    test_case_id=test_case_id,
                    app_url=app_url or None,
                    browser="chromium",
                    headless=True,
                    save_to_db=True,
                )

        asyncio.create_task(_run_in_bg())

        url_note = f" against **{app_url}**" if app_url else ""
        return (
            f"## Execution Started\n\n"
            f"Running **{tc_code}: {tc_title[:60]}**{url_note}.\n\n"
            f"- Execution is running in the background.\n"
            f"- Live step-by-step output is visible on the **Playwright Scripts** page.\n"
            f"- Results are saved automatically when it finishes.\n\n"
            f"Use `get_suite_results` after completion to see the final outcome."
        )

    @tool("run_test_suite")
    async def run_test_suite(
        suite_id: str,
        app_url: str = "",
    ) -> str:
        """
        Execute all test cases in a test suite using a single optimised browser session.
        Missing scripts are generated automatically before execution starts.
        Execution runs in the background — the user can watch live progress on the
        Test Suite detail page.

        Args:
            suite_id: The UUID of the test suite to run (from get_test_suites)
            app_url: The base URL of the application under test (e.g. "http://localhost:3000")
        """
        import asyncio
        from app.services.playwright_service import run_suite_smart
        from app.models.test_suite import TestSuite as TS

        async with async_session_maker() as db:
            suite: TS | None = await db.get(TS, suite_id)
            if not suite:
                return f"Test suite `{suite_id}` not found."
            suite_title = suite.title

            # Quick TC count
            from sqlalchemy import select, func
            from app.models.test_case import TestCase
            cnt_r = await db.execute(
                select(func.count(TestCase.id))
                .where(TestCase.test_suite_id == suite_id, TestCase.is_active == True)
            )
            tc_count = cnt_r.scalar() or 0

        if tc_count == 0:
            return f"Suite **{suite_title}** has no active test cases to run."

        async def _run_in_bg():
            async with async_session_maker() as db:
                await run_suite_smart(
                    db,
                    suite_id=suite_id,
                    app_url=app_url or None,
                    browser="chromium",
                    headless=True,
                    stop_on_failure=False,
                )

        asyncio.create_task(_run_in_bg())

        url_note = f" against **{app_url}**" if app_url else ""
        return (
            f"## Suite Execution Started\n\n"
            f"Running **{suite_title}** ({tc_count} test cases){url_note}.\n\n"
            f"- Missing scripts will be auto-generated before execution.\n"
            f"- A single browser session is reused across all TCs for speed.\n"
            f"- Live progress is visible on the **Test Suite** detail page.\n"
            f"- Results are saved automatically when it finishes.\n\n"
            f"Use `get_suite_results('{suite_id}')` after it completes to see the outcome."
        )

    return [refine_user_story, generate_test_cases, generate_playwright_script,
            execute_playwright_script, run_test_suite]
