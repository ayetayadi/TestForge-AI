from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.run_pipeline_request import RunPipelineRequest
from app.services.pipeline_service import start_pipeline
from app.services.stories_service import (
    list_stories,
    list_stories_by_project,
)

router = APIRouter(prefix="/stories", tags=["Stories"])


# =========================
# GET ALL STORIES
# =========================
@router.get("")
async def get_stories(db: AsyncSession = Depends(get_db)):
    return await list_stories(db)


# =========================
# GET STORIES BY PROJECT
# =========================
@router.get("/by-project/{project_id}")
async def get_stories_by_project_id(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    return await list_stories_by_project(db, project_id)


# =========================
# RUN PIPELINE
# =========================
@router.post("/pipeline/run")
async def run_pipeline_endpoint(
    data: RunPipelineRequest,
    db: AsyncSession = Depends(get_db),
):
    if data.type == "keys":
        jobs = await start_pipeline(db, issue_keys=data.issue_keys)

    elif data.type == "project":
        jobs = await start_pipeline(db, project_id=data.project_id)

    else:
        raise HTTPException(status_code=400, detail="Invalid type")

    return {
        "status": "started",
        "jobs": jobs,
    }