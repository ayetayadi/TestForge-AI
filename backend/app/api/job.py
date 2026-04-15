# ============================================================
# api/routes/jobs_routes.py (CORRIGÉ)
# ============================================================
"""
Jobs endpoints.

Gère:
- GET job status
- POST job decision (approve/reject)
- SSE streaming
- Resume (utilise orchestrator)
"""

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories.job_repository import get_job_by_id, get_active_jobs
from app.services.job_service import apply_decision, get_jobs_by_issue_keys
from app.streaming.sse_manager import event_generator
from app.repositories.user_story_version_repository import get_latest_version
from app.models.enums import JobStatus

class DecisionRequest(BaseModel):
    """Decision request payload"""
    decision: str
    version_id: Optional[str] = None


router = APIRouter(prefix="/jobs", tags=["jobs"])


# ============================================================
# SSE STREAMING
# ============================================================

@router.get("/{job_id}/stream")
async def stream_job(request: Request, job_id: str):
    """
    Stream job progress via SSE.
    
    Returns:
        SSE stream with events: processing, completed, failed
    """
    
    return StreamingResponse(
        event_generator(job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# GET JOB STATE
# ============================================================

@router.get("/{job_id}")
async def get_job_state(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get complete job state and result.
    
    Args:
        job_id: Job ID
        
    Returns:
        Job info with status, scores, story, AC
    """
    
    job = await get_job_by_id(db, job_id)

    if not job:
        raise HTTPException(404, "Job not found")
    
    # Get latest version
    latest = None
    if job.versions:
        latest = max(job.versions, key=lambda v: v.iteration or 0)
    else:
        # Fallback: query latest version
        latest = await get_latest_version(db, job.user_story_id)

    story = job.user_story

    return {
        "job_id": job.id,
        "status": job.status.value if job.status else None,
        "phase": job.phase.value if job.phase else None,
        "iteration": job.iteration or 0,
        "started_at": job.started_at,
        "completed_at": job.completed_at,

        "user_story_id": job.user_story_id,
        "issue_key": story.issue_key if story else None,
        "project_id": story.project_id if story else None,

        "initial_story": story.description if story else None,
        "existing_ac": story.acceptance_criteria or [],

        "version_id": latest.id if latest else None,
        "improved_story": latest.improved_story if latest else None,
        "generated_acceptance_criteria": (
            latest.generated_acceptance_criteria if latest else []
        ),
        "initial_score": latest.initial_score if latest else 0,
        "final_score": latest.final_score if latest else 0,
        "testability_score": latest.testability_score if latest else None,
        "is_testable": latest.is_testable if latest else None,
        "testability_issues": latest.testability_issues or [],
        "score_delta": (
            (latest.final_score - latest.initial_score)
            if latest and latest.initial_score is not None
            and latest.final_score is not None
            else 0
        ),
    }


# ============================================================
# GET ACTIVE JOBS
# ============================================================

@router.get("/active/list")
async def get_active_jobs_route(db: AsyncSession = Depends(get_db)):
    """
    Get all active jobs.
    
    Returns:
        List of active jobs
    """
    
    jobs = await get_active_jobs(db)

    return [
        {
            "job_id": j.id,
            "status": j.status.value if j.status else None,
            "phase": j.phase.value if j.phase else None,
            "iteration": j.iteration or 0,
        }
        for j in jobs
    ]


# ============================================================
# APPLY DECISION
# ============================================================

@router.post("/{job_id}/decision")
async def apply_job_decision(
    job_id: str,
    request: DecisionRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Apply decision to a job version.
    
    Decisions:
    - approve: Mark version as approved
    - reject_relaunch: Reject and start new job
    - reject_keep: Reject but keep original
    
    Args:
        job_id: Job ID
        request: DecisionRequest with decision + version_id
        
    Returns:
        Decision result
    """
    
    job = await get_job_by_id(db, job_id)

    if not job:
        raise HTTPException(404, "Job not found")

    if request.decision not in ("approve", "reject_relaunch", "reject_keep"):
        raise HTTPException(400, "Invalid decision")

    if request.decision in ("approve", "reject_relaunch") and not request.version_id:
        raise HTTPException(400, "version_id required for this decision")

    result = await apply_decision(
        db=db,
        user_story_id=job.user_story_id,
        decision=request.decision,
        version_id=request.version_id
    )
    
    # Add issue_key for frontend
    if job.user_story:
        result["issue_key"] = job.user_story.issue_key
    
    return result


# ============================================================
# GET JOBS BY ISSUE KEYS
# ============================================================

@router.post("/by-issues")
async def get_jobs_by_issues(
    issue_keys: List[str] = Body(...),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Get jobs for multiple issue keys.
    
    Args:
        issue_keys: List of Jira issue keys
        
    Returns:
        Dict mapping issue_key → job info
    """

    if not issue_keys:
        raise HTTPException(400, "issue_keys required")

    return await get_jobs_by_issue_keys(db, issue_keys)