from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.enums import DefectStatus
from app.services.defect_service import (
    get_all_defects,
    get_notifications_by_story,
    update_defect_status,
)

router = APIRouter(prefix="/defects", tags=["defects"])


class StatusUpdateRequest(BaseModel):
    status: DefectStatus


@router.get("")
@router.get("/", include_in_schema=False)
async def list_defects(db: AsyncSession = Depends(get_db)):
    """Return all defects across all projects."""
    return await get_all_defects(db)


@router.get("/by-story/{user_story_id}")
async def list_notifications_by_story(user_story_id: str, db: AsyncSession = Depends(get_db)):
    """Return all quality notifications for a specific user story.

    Defects are now tied to test cases, not user stories. Story-level quality
    alerts live in the notifications table, so this endpoint returns those.
    """
    return await get_notifications_by_story(db, user_story_id)


@router.patch("/{defect_id}/status")
async def patch_defect_status(
    defect_id: str,
    body: StatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update the status of a defect (open → in_progress → resolved → closed)."""
    updated = await update_defect_status(db, defect_id, body.status)
    if not updated:
        raise HTTPException(404, "Defect not found")
    return updated
