"""
AI test case generation endpoint.
POST /ai-generate/test-cases/{user_story_id}
  → runs the TestCaseGenerator agent against the given user story
  → saves all generated test cases to the DB
  → returns the created test cases
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.test_case import TestCase
from app.models.user_story import UserStory
from app.services import test_case_service
from app.ai_agents_v2.test_case_generator.runner import run_test_case_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai-generate", tags=["AI Generate"])


# ── Response schema ────────────────────────────────────────────────────────────

class GeneratedTestCaseResponse(BaseModel):
    id: str
    tc_code: str
    title: str
    description: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None
    steps: Optional[List[Dict]] = None
    gherkin_source: Optional[str] = None
    test_data: Optional[Dict[str, Any]] = None
    user_story_id: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None


class GenerateTestCasesResponse(BaseModel):
    generated_count: int
    quality_score: int
    flagged_for_human: bool
    user_story_analysis: Optional[Dict[str, Any]] = None
    test_cases: List[GeneratedTestCaseResponse]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_module(issue_key: str) -> str:
    """SCRUM-5 → SCRUM, PROJ-123 → PROJ, plain → PLAIN"""
    match = re.match(r"^([A-Z0-9]+)-", issue_key.upper())
    return match.group(1) if match else re.sub(r"[^A-Z]", "", issue_key.upper()) or "GEN"


async def _next_tc_codes(db: AsyncSession, module: str, count: int) -> List[str]:
    """Generate `count` unique tc_codes with the given module prefix."""
    prefix = f"TC-{module}-"
    result = await db.execute(
        select(TestCase.tc_code).where(TestCase.tc_code.like(f"{prefix}%"))
    )
    existing_numbers = []
    for (code,) in result.fetchall():
        m = re.search(r"-(\d+)$", code)
        if m:
            existing_numbers.append(int(m.group(1)))

    start = max(existing_numbers, default=0) + 1
    return [f"{prefix}{start + i:03d}" for i in range(count)]


def _map_priority(qforge_priority: str) -> str:
    mapping = {"high": "high", "medium": "medium", "low": "low", "critical": "critical"}
    return mapping.get(qforge_priority.lower(), "medium")


def _map_steps(qforge_steps: List[Dict]) -> List[Dict]:
    return [
        {
            "order": s.get("step_number", i + 1),
            "action": s.get("description", ""),
            "expected": s.get("expected_result", ""),
        }
        for i, s in enumerate(qforge_steps)
    ]


def _build_tags(qforge_tc: Dict) -> List[str]:
    tags = list(qforge_tc.get("tags") or [])
    test_type = (qforge_tc.get("test_type") or "positive").lower().replace(" ", "-")
    if test_type and test_type not in tags:
        tags.append(test_type)
    return tags


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/test-cases/{user_story_id}", response_model=GenerateTestCasesResponse)
async def generate_test_cases(
    user_story_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Run the AI test case generator agent for the given user story
    and persist all generated test cases to the database.
    """
    # 1. Load the user story
    user_story: Optional[UserStory] = await db.get(UserStory, user_story_id)
    if not user_story:
        raise HTTPException(status_code=404, detail="User story not found")

    story_text = f"As a user, {user_story.description or user_story.title}"
    acceptance_criteria: List[str] = [
        str(ac).strip()
        for ac in (user_story.acceptance_criteria or [])
        if ac and str(ac).strip()
    ]

    logger.info(
        "[ai_generate] Generating test cases for story=%s (%s ACs)",
        user_story.issue_key, len(acceptance_criteria),
    )

    # 2. Run the agent
    try:
        result = await run_test_case_agent(
            user_story=story_text,
            acceptance_criteria=acceptance_criteria,
        )
    except Exception as exc:
        logger.exception("[ai_generate] Agent failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")

    raw_test_cases: List[Dict] = result.get("test_cases") or []
    flagged = result.get("flagged_for_human", False)

    # Agent flagged with no usable test cases — return a structured warning, not a 500/422
    if not raw_test_cases:
        if flagged:
            return GenerateTestCasesResponse(
                generated_count=0,
                quality_score=0,
                flagged_for_human=True,
                user_story_analysis=result.get("user_story_analysis"),
                test_cases=[],
            )
        raise HTTPException(
            status_code=422,
            detail="The agent did not generate any test cases. Try again or check your story content.",
        )

    # 3. Generate tc_codes
    module = _extract_module(user_story.issue_key or "GEN")
    tc_codes = await _next_tc_codes(db, module, len(raw_test_cases))

    # 4. Persist each test case
    created: List[TestCase] = []
    for i, tc in enumerate(raw_test_cases):
        data = {
            "tc_code":        tc_codes[i],
            "title":          tc.get("name") or f"Test Case {i + 1}",
            "description":    tc.get("description") or None,
            "priority":       _map_priority(tc.get("priority") or "Medium"),
            "tags":           _build_tags(tc),
            "steps":          _map_steps(tc.get("steps") or []),
            "gherkin_source": tc.get("gherkin_scenario") or None,
            "test_data":      tc.get("test_data") or None,
            "user_story_id":  user_story_id,
            "preconditions":  [],
            "postconditions": [],
            "expected_results": [],
            "is_active": True,
        }
        try:
            test_case = await test_case_service.create_test_case(db, data)
            created.append(test_case)
        except Exception as exc:
            logger.warning("[ai_generate] Skipping tc %s: %s", tc_codes[i], exc)

    if not created:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save generated test cases")

    await db.commit()

    logger.info("[ai_generate] Saved %d test cases for story=%s", len(created), user_story.issue_key)

    # 5. Return
    return GenerateTestCasesResponse(
        generated_count=len(created),
        quality_score=result.get("last_critic_score", 0),
        flagged_for_human=result.get("flagged_for_human", False),
        user_story_analysis=result.get("user_story_analysis"),
        test_cases=[
            GeneratedTestCaseResponse(
                id=tc.id,
                tc_code=tc.tc_code,
                title=tc.title,
                description=tc.description,
                priority=tc.priority,
                tags=tc.tags,
                steps=tc.steps,
                gherkin_source=tc.gherkin_source,
                test_data=tc.test_data,
                user_story_id=tc.user_story_id,
                is_active=tc.is_active,
                created_at=tc.created_at.isoformat() if tc.created_at else None,
            )
            for tc in created
        ],
    )
