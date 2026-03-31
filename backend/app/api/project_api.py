from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.project_service import (
    get_projects,
    import_project_by_key,
)

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("/")
async def list_projects(db: AsyncSession = Depends(get_db)):
    return await get_projects(db)


@router.post("/{project_key}/import")
async def import_project(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await import_project_by_key(db, project_key, current_user)