from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories.user_story_version_repository import get_versions_by_story_id
from app.services.user_story_service import (
    list_stories,
    get_user_story_details,
    list_stories_by_project,
    get_story_by_issue_key
)

router = APIRouter(prefix="/user-stories", tags=["user-stories"])
@router.get("/")
async def get_user_stories(db: AsyncSession = Depends(get_db)):
    return await list_stories(db)


@router.get("/{user_story_id}")
async def get_user_story(user_story_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return await get_user_story_details(db, user_story_id)
    except ValueError:
        raise HTTPException(404, "User story not found")


@router.get("/by-project/{project_id}")
async def get_user_stories_by_project(project_id: str, db: AsyncSession = Depends(get_db)):
    return await list_stories_by_project(db, project_id)

@router.get("/by-issue-key/{issue_key}")
async def get_user_story_by_issue_key(issue_key: str, db: AsyncSession = Depends(get_db)):
    try:
        return await get_story_by_issue_key(db, issue_key)
    except ValueError:
        raise HTTPException(404, "User story not found")
    

@router.get("/{story_id}/versions")
async def get_story_versions(
    story_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Retourne toutes les versions d'une story"""
    versions = await get_versions_by_story_id(db, story_id)
    
    return [
        {
            "id": v.id,
            "story_id": v.user_story_id,
            "improved_story": v.improved_story,
            "generated_acceptance_criteria": v.generated_acceptance_criteria,
            "initial_score": v.initial_score,
            "final_score": v.final_score,
            "score_delta": (
                (v.final_score - v.initial_score)
                if v.initial_score is not None and v.final_score is not None
                else 0
            ),
            "started_at": v.started_at.isoformat() if v.started_at else None,
            "completed_at": v.completed_at.isoformat() if v.completed_at else None,
            "decision_status": (
                v.decision_status.value if v.decision_status else "pending"
            ),
            "testability_score": v.testability_score,
            "is_testable": v.is_testable,
            "testability_issues": v.testability_issues or [],
            "agent_status": v.agent_status.value if v.agent_status else "processing",
            "model_used": v.model_used,
            "llm_calls": v.llm_calls,
            "prompt_tokens": v.prompt_tokens,
            "completion_tokens": v.completion_tokens,
            "duration": v.duration,
        }
        for v in versions
    ]