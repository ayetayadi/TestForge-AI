from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from app.services.job_service import get_job_state, apply_decision, get_pending_jobs
from app.streaming.sse_manager import event_generator
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/pending")
def pending_jobs():
    return get_pending_jobs()


@router.get("/{job_id}")
async def get_job(job_id: str):
    return await get_job_state(job_id)


@router.get("/{job_id}/stream")
async def stream(job_id: str, request: Request):
    return StreamingResponse(
        event_generator(job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{job_id}/decision")
def decision(job_id: str, choice: str):
    return apply_decision(job_id, choice)