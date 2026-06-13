from app.api.deps import get_current_user
from app.models.user import User
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.core.database import get_db
from app.models.test_plan import TestPlan
from app.services.project_service import (
    delete_project,
    import_project_by_key,
    get_all_projects,
)

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("", status_code=status.HTTP_200_OK)
@router.get("/", status_code=status.HTTP_200_OK, include_in_schema=False)
async def get_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await get_all_projects(db, user_id=current_user.id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{project_key}/import")
async def import_project(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    epic_key: str | None = Query(default=None, description="Import only stories under this epic (e.g. PROJ-1)"),
    sprint_name: str | None = Query(default=None, description="Import only stories in this sprint (exact name)"),
    use_or: bool = False,
):
    return await import_project_by_key(
        db, project_key, current_user,
        epic_key=epic_key,
        sprint_name=sprint_name,
        use_or=use_or
    )


@router.get("/{project_id}/test-plans", status_code=status.HTTP_200_OK)
async def get_project_test_plans(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return all test plans for a given project."""
    stmt = (
        select(
            TestPlan.id,
            TestPlan.title,
            TestPlan.status,
            TestPlan.created_at,
        )
        .where(TestPlan.project_id == project_id)
        .order_by(TestPlan.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.mappings().all()
    return [dict(r) for r in rows]


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