from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.project_service import (
    import_project_by_key,
    get_projects,
    get_jira_projects
)

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("/")
def list_projects(db: Session = Depends(get_db)):
    return get_projects(db)


@router.get("/jira")
def list_jira_projects():
    return get_jira_projects()


@router.post("/{project_key}/import")
def import_stories(project_key: str, db: Session = Depends(get_db)):
    return import_project_by_key(db, project_key)