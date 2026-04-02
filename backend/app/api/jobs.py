from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.jobs_service import (
    get_job_state,
    apply_decision,
    get_pending_jobs,
)
from app.streaming.sse_manager import event_generator

router = APIRouter(prefix="/jobs", tags=["Jobs"])


# =========================
# GET ALL PENDING JOBS
# =========================
@router.get("/pending")
async def get_pending():
    return await get_pending_jobs()

# =========================
# GET JOB BY ID
# =========================
@router.get("/{job_id}")
async def get_job(job_id: str):
    return await get_job_state(job_id)


# =========================
# STREAM JOB EVENTS
# =========================
@router.get("/{job_id}/stream")
async def stream_job(job_id: str, request: Request):
    return StreamingResponse(
        event_generator(job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =========================
# APPLY DECISION
# =========================
@router.post("/{job_id}/decision")
async def apply_job_decision(job_id: str, choice: str):
    return await apply_decision(job_id, choice)