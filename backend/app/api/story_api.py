from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.story_service import (
    list_stories,
    list_stories_by_project
)
from app.services.pipeline_service import start_pipeline

from app.schemas.run_pipeline_request import RunPipelineRequest

router = APIRouter(prefix="/stories", tags=["User Stories"])


@router.get("/")
def get_all(db: Session = Depends(get_db)):
    return list_stories(db)


@router.get("/project/{project_id}")
def get_by_project(project_id: str, db: Session = Depends(get_db)):
    return list_stories_by_project(db, project_id)


@router.post("/pipeline")
def run_pipeline(data: RunPipelineRequest, db: Session = Depends(get_db)):
    if data.type == "keys":
        jobs = start_pipeline(db, issue_keys=data.issue_keys)

    elif data.type == "project":
        jobs = start_pipeline(db, project_id=data.project_id)

    else:
        raise HTTPException(400, "Invalid type")

    return {
        "status": "started",
        "jobs": jobs
    }