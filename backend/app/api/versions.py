"""
Versions endpoints.

Gère:
- GET version status
- POST version decision (approve/reject)
- SSE streaming
- Resume (utilise orchestrator)
"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Body, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.user_story_version_service import (
    apply_decision,
    can_edit,
    delete_version,
    edit_version,
    get_versions_by_issue_keys,
    reset_to_original,
    start_version
)
from app.repositories.user_story_version_repository import (
    get_version_by_id,
    get_latest_version,
    get_versions_by_story_id
)
from app.repositories.user_story_repository import get_user_story_by_id, get_user_story_by_issue_key
from app.streaming.sse_manager import event_generator
from app.models.enums import WorkflowStatus
from app.workers.us_worker import submit_version


class DecisionRequest(BaseModel):
    """Decision request payload"""
    decision: str
    version_id: Optional[str] = None


class StartVersionRequest(BaseModel):
    """Start version request payload"""
    reset: bool = False


router = APIRouter(prefix="/versions", tags=["versions"])


# ============================================================
# SSE STREAMING
# ============================================================

@router.get("/{version_id}/stream")
async def stream_version(request: Request, version_id: str):
    """
    Stream version progress via SSE.
    
    Returns:
        SSE stream with events: processing, completed, failed
    """
    
    return StreamingResponse(
        event_generator(version_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# GET VERSION STATE
# ============================================================

@router.get("/{version_id}")
async def get_version_state(version_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get complete version state and result.
    
    Args:
        version_id: Version ID
        
    Returns:
        Version info with status, scores, story, AC
    """
    
    version = await get_version_by_id(db, version_id)

    if not version:
        raise HTTPException(404, "Version not found")
    
    # Get user story
    story = await get_user_story_by_id(db, version.user_story_id)

    return {
        "version_id": version.id,
        "workflow_status": version.workflow_status.value if version.workflow_status else None,
        "decision_status": version.decision_status.value if version.decision_status else "pending",
        "started_at": version.started_at,
        "completed_at": version.completed_at,

        "user_story_id": version.user_story_id,
        "issue_key": story.issue_key if story else None,
        "project_id": story.project_id if story else None,

        "initial_story": story.description if story else None,
        "existing_ac": story.acceptance_criteria or [],

        "improved_story": version.improved_story,
        "generated_acceptance_criteria": version.generated_acceptance_criteria or [],
        "initial_score": version.initial_score or 0,
        "final_score": version.final_score or 0,
        "testability_score": version.testability_score,
        "is_testable": version.is_testable,
        "testability_issues": version.testability_issues or [],
        "score_delta": (
            (version.final_score - version.initial_score)
            if version.initial_score is not None and version.final_score is not None
            else 0
        ),
    }


# ============================================================
# GET ACTIVE VERSIONS
# ============================================================

@router.get("/active/list")
async def get_active_versions(db: AsyncSession = Depends(get_db)):
    """
    Get all active versions (processing).
    
    Returns:
        List of active versions
    """
    
    from sqlalchemy import select
    from app.models.user_story_version import UserStoryVersion
    
    result = await db.execute(
        select(UserStoryVersion)
        .where(UserStoryVersion.workflow_status == WorkflowStatus.PROCESSING)
        .order_by(UserStoryVersion.started_at.desc())
    )
    versions = result.scalars().all()

    return [
        {
            "version_id": v.id,
            "workflow_status": v.workflow_status.value,
            "started_at": v.started_at,
            "user_story_id": v.user_story_id,
        }
        for v in versions
    ]


# ============================================================
# START NEW VERSION
# ============================================================

@router.post("/start/{story_id}")
async def start_new_version(
    story_id: str,
    request: StartVersionRequest = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Start a new version for a user story.
    
    Args:
        story_id: User story ID
        reset: If True, use original story instead of latest version
        
    Returns:
        Version info
    """
    
    story = await get_user_story_by_id(db, story_id)
    
    if not story:
        raise HTTPException(404, "User story not found")
    
    reset = request.reset if request else False
    
    version_id, state = await start_version(db, story, reset=reset)
    
    # Submit to queue
    try:
        await submit_version(state)
    except Exception as e:
        raise HTTPException(500, f"Failed to submit version: {e}")
    
    return {
        "version_id": version_id,
        "status": "processing",
        "message": "Version started successfully"
    }


# ============================================================
# APPLY DECISION
# ============================================================

@router.post("/{version_id}/decision")
async def apply_version_decision(
    version_id: str,
    request: DecisionRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Apply decision to a version.
    
    Decisions:
    - approve: Mark version as approved
    - relaunch: Start new version
    - reject_keep: Reject but keep original
    
    Args:
        version_id: Version ID
        request: DecisionRequest with decision
        
    Returns:
        Decision result
    """
    
    version = await get_version_by_id(db, version_id)

    if not version:
        raise HTTPException(404, "Version not found")

    if request.decision not in ("approve", "relaunch", "reject_keep"):
        raise HTTPException(400, "Invalid decision. Use: approve, relaunch, reject_keep")

    result = await apply_decision(
        db=db,
        user_story_id=version.user_story_id,
        decision=request.decision,
        version_id=version_id
    )
    
    return result


# ============================================================
# GET VERSIONS BY ISSUE KEYS
# ============================================================

@router.post("/by-issue-keys")
async def get_versions_by_issue_keys_endpoint(
    issue_keys: List[str] = Body(..., embed=False),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get versions for multiple issue keys.
    
    Args:
        issue_keys: List of Jira issue keys
        
    Returns:
        Dict mapping issue_key → version info
    """

    if not issue_keys:
        raise HTTPException(400, "issue_keys required")

    return await get_versions_by_issue_keys(db, issue_keys)


# ============================================================
# GET VERSIONS BY STORY ID
# ============================================================

@router.get("/story/{story_id}")
async def get_story_versions(
    story_id: str,
    limit: int = Query(50, ge=1, le=200),
    status: Optional[WorkflowStatus] = Query(None, description="Filter by agent status"),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all versions for a user story.
    
    Args:
        story_id: User story ID
        limit: Maximum number of versions
        status: Filter by agent status
        
    Returns:
        List of versions
    """
    
    story = await get_user_story_by_id(db, story_id)
    if not story:
        raise HTTPException(404, "User story not found")
    
    versions = await get_versions_by_story_id(db, story_id)
    
    if status:
        versions = [v for v in versions if v.workflow_status == status]
    
    versions = versions[:limit]
    
    return [
        {
            "id": v.id,
            "workflow_status": v.workflow_status.value,
            "decision_status": v.decision_status.value,
            "improved_story": v.improved_story,
            "generated_acceptance_criteria": v.generated_acceptance_criteria,
            "initial_score": v.initial_score,
            "final_score": v.final_score,
            "testability_score": v.testability_score,
            "is_testable": v.is_testable,
            "started_at": v.started_at,
            "completed_at": v.completed_at,
        }
        for v in versions
    ]


# ============================================================
# GET LATEST VERSION BY ISSUE KEY
# ============================================================

@router.get("/latest/{issue_key}")
async def get_latest_version_by_issue_key(
    issue_key: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get the latest version for a Jira issue.
    
    Args:
        issue_key: Jira issue key (ex: PROJ-123)
        
    Returns:
        Latest version info
    """
    
    story = await get_user_story_by_issue_key(db, issue_key)
    
    if not story:
        raise HTTPException(404, f"User story {issue_key} not found")
    
    latest = await get_latest_version(db, story.id)
    
    if not latest:
        raise HTTPException(404, f"No version found for {issue_key}")
    
    return {
        "version_id": latest.id,
        "issue_key": story.issue_key,
        "workflow_status": latest.workflow_status.value,
        "decision_status": latest.decision_status.value,
        "improved_story": latest.improved_story,
        "generated_acceptance_criteria": latest.generated_acceptance_criteria,
        "initial_score": latest.initial_score,
        "final_score": latest.final_score,
        "testability_score": latest.testability_score,
        "is_testable": latest.is_testable,
        "started_at": latest.started_at,
        "completed_at": latest.completed_at,
    }


# ============================================================
# EDIT VERSION (MODIFIER MANUELLEMENT)
# ============================================================

class EditVersionRequest(BaseModel):
    """Requête pour modifier une version"""
    improved_story: str
    acceptance_criteria: List[str]


class EditVersionResponse(BaseModel):
    """Réponse après modification"""
    status: str
    message: str
    version_id: str
    is_customized: bool
    customized_at: Optional[str] = None


class CanEditResponse(BaseModel):
    """Vérification si une version est modifiable"""
    can_edit: bool
    reason: Optional[str] = None
    is_approved: bool
    is_customized: bool


class ResetCustomizationResponse(BaseModel):
    """Réponse après réinitialisation"""
    status: str
    message: str
    version_id: str
    is_customized: bool
    customized_at: Optional[str] = None


@router.put("/{version_id}/edit", response_model=EditVersionResponse)
async def edit_version_endpoint(
    version_id: str,
    request: EditVersionRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        print(f"[DEBUG] Editing version: {version_id}")
        print(f"[DEBUG] Story: {request.improved_story[:50]}...")
        print(f"[DEBUG] AC count: {len(request.acceptance_criteria)}")
        
        result = await edit_version(
            db=db,
            version_id=version_id,
            improved_story=request.improved_story,
            acceptance_criteria=request.acceptance_criteria,
            user_id=None
        )
        print(f"[DEBUG] Result: {result}")
        return result
    except ValueError as e:
        print(f"[ERROR] ValueError: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        print(f"[ERROR] PermissionError: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        print(f"[ERROR] Exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{version_id}/can-edit", response_model=CanEditResponse)
async def can_edit_version_endpoint(
    version_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Vérifie si une version peut être modifiée.
    
    Une version est modifiable si:
    - Elle existe
    - Elle n'est pas approuvée (decision_status != APPROVED)
    """
        
    try:
        result = await can_edit(db=db, version_id=version_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{version_id}/reset-customization", response_model=ResetCustomizationResponse)
async def reset_customization_endpoint(
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Réinitialise le flag is_customized d'une version à False.
    
    Attention: Ne restaure PAS le contenu original.
    """
    
    try:
        result = await reset_to_original(
            db=db,
            version_id=version_id
        )
        return result
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# DELETE VERSION
# ============================================================

@router.delete("/{version_id}")
async def delete_version_endpoint(
    version_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a refined version.
    Approved and currently processing versions cannot be deleted.
    """
    try:
        return await delete_version(db, version_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))