from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.run_pipeline_request import RunPipelineRequest
from app.services.pipeline_service import start_pipeline
from app.services.story_service import (
    list_stories,
    list_stories_by_project,
)

router = APIRouter(prefix="/stories", tags=["User Stories"])


@router.get("/")
async def get_all(db: AsyncSession = Depends(get_db)):
    return await list_stories(db)


@router.get("/project/{project_id}")
async def get_by_project(project_id: str, db: AsyncSession = Depends(get_db)):
    return await list_stories_by_project(db, project_id)


@router.post("/pipeline")
async def run_pipeline(data: RunPipelineRequest, db: AsyncSession = Depends(get_db)):
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