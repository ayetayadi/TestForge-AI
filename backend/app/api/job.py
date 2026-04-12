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
from app.workers.asyncio_workers import submit_job
from app.ai_agents.user_stories.graph import build_graph
graph = build_graph()

class DecisionRequest(BaseModel):
    decision: str
    version_id: Optional[str] = None


router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get_latest_version(job):
    """Retourne la dernière version d'un job"""
    if not job.versions:
        return None
    return max(job.versions, key=lambda v: v.iteration)


@router.get("/{job_id}/stream")
async def stream_job(request: Request, job_id: str):
    return StreamingResponse(
        event_generator(job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.get("/{job_id}")
async def get_job_state(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await get_job_by_id(db, job_id)

    if not job:
        raise HTTPException(404, "Job not found")
    latest = _get_latest_version(job)
    if not latest:
        latest = await get_latest_version(db, job.user_story_id)

    story = job.user_story

    return {
        "job_id": job.id,
        "status": job.status.value if job.status else None,
        "phase": job.phase.value if job.phase else None,
        "iteration": job.iteration,
        "started_at": job.started_at,
        "completed_at": job.completed_at,

        "user_story_id": job.user_story_id if job.user_story_id else None,
        "issue_key": story.issue_key if story else None,
        "project_id": story.project_id if story else None,

        "initial_story": story.description if story else None,
        "raw_story": story.description if story else None,
        "existing_ac": story.acceptance_criteria if story else [],

        "version_id": latest.id if latest else None,
        "improved_story": latest.improved_story if latest else None,
        "generated_acceptance_criteria": latest.generated_acceptance_criteria if latest else [],
        "initial_score": latest.initial_score if latest else 0,
        "final_score": latest.final_score if latest else 0,
        "testability_score": latest.testability_score if latest else None,
        "is_testable": latest.is_testable if latest else None,
        "testability_issues": latest.testability_issues if latest else [],
        "score_delta": (
            (latest.final_score - latest.initial_score)
            if latest and latest.initial_score is not None and latest.final_score is not None
            else 0
        ),

        "is_reused": latest is not None and not job.versions
    }

@router.get("/active/list")
async def get_active_jobs_route(db: AsyncSession = Depends(get_db)):
    jobs = await get_active_jobs(db)

    return [
        {
            "job_id": j.id,
            "status": j.status,
            "phase": j.phase,
            "iteration": j.iteration,
        }
        for j in jobs
    ]


@router.post("/{job_id}/decision")
async def apply_job_decision(
    job_id: str,
    request: DecisionRequest,
    db: AsyncSession = Depends(get_db)
):
    job = await get_job_by_id(db, job_id)

    if not job:
        raise HTTPException(404, "Job not found")

    if request.decision not in ("approve", "reject_relaunch", "reject_keep"):
        raise HTTPException(400, "Invalid decision")

    if request.decision == "approve" and not request.version_id:
        raise HTTPException(400, "version_id is required for approval")

    result = await apply_decision(
        db=db,
        user_story_id=job.user_story_id,
        decision=request.decision,
        version_id=request.version_id
    )
    
    # Ajouter issue_key pour le frontend (relaunch)
    if job.user_story:
        result["issue_key"] = job.user_story.issue_key
    
    return result


@router.post("/by-issues")
async def get_jobs_by_issues(
    issue_keys: List[str] = Body(...),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:

    if not issue_keys:
        return {}

    return await get_jobs_by_issue_keys(db, issue_keys)



@router.post("/{job_id}/resume")
async def resume_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Reprendre un job échoué depuis son dernier checkpoint.
    """
    job = await get_job_by_id(db, job_id)
    
    if not job:
        raise HTTPException(404, "Job not found")
    
    if job.status != JobStatus.FAILED:
        raise HTTPException(400, "Job is not in failed state")
    
    # Vérifier s'il y a un checkpoint
    config = {"configurable": {"thread_id": f"job-{job_id}"}}
    
    try:
        state = graph.get_state(config)
        if not state or not state.values:
            raise HTTPException(400, "No checkpoint found for this job")
        
        # Remettre le job dans la queue
        await submit_job({
            **state.values,
            "job_id": job_id,
            "is_retry": True
        })
        
        return {"message": "Job resumed", "last_node": state.next}
        
    except Exception as e:
        raise HTTPException(500, f"Failed to resume: {e}")


@router.get("/{job_id}/state")
async def get_job_state(job_id: str):
    """
    Voir l'état actuel du checkpoint (debug).
    """
    config = {"configurable": {"thread_id": f"job-{job_id}"}}
    
    state = graph.get_state(config)
    
    if not state:
        return {"checkpoint": None}
    
    return {
        "checkpoint": {
            "values": state.values,
            "next": state.next,  # Prochain node à exécuter
            "config": state.config,
        }
    }