from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.project_service import (
    import_project_by_key,
    get_projects,
    get_jira_projects
)

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("/")
async def list_projects(db: AsyncSession = Depends(get_db)):
    return await get_projects(db)


@router.get("/jira")
async def list_jira_projects():
    return await get_jira_projects()


@router.post("/{project_key}/import")
async def import_stories(project_key: str, db: AsyncSession = Depends(get_db)):
    return await import_project_by_key(db, project_key)