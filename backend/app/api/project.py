from app.api.deps import get_current_user
from app.models.user import User
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.core.database import get_db
from app.services.project_service import (
    delete_project,
    import_project_by_key,
    get_all_projects,
)

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("/", status_code=status.HTTP_200_OK)
async def get_projects(
    db: AsyncSession = Depends(get_db)
):
    try:
        return await get_all_projects(db)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)  # utile en dev
        )


@router.post("/{project_key}/import")
async def import_project(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await import_project_by_key(db, project_key, current_user)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_endpoint(
    project_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    try:
        await delete_project(db, str(project_id))
        return

    except ValueError:
        raise HTTPException(404, "Project not found")

    except Exception as e:
        raise HTTPException(500, str(e))