"""
Notifications API

Endpoints:
  GET  /notifications/{project_key}          — list persisted notifications
  POST /notifications/{id}/read              — mark one notification as read
  POST /notifications/{project_key}/read-all — mark all as read for a project
  GET  /notifications/stream/{project_key}   — SSE real-time stream
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.core.database import get_db
from app.api.deps import get_current_user
from app.core.security import decode_access_token
from app.models.user import User
from app.models.notification import Notification
from app.streaming.sse_manager import sse_endpoint

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/stream/{project_key}")
async def notification_stream(
    project_key: str,
    request: Request,
    token: str = Query(..., description="JWT access token (EventSource cannot send headers)"),
    db: AsyncSession = Depends(get_db),
):
    """
    SSE stream for real-time notifications.
    Token is passed as query param because EventSource does not support headers.
    Channel key: "notifications:{project_key}"
    """
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == payload.get("sub")))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    channel = f"notifications:{project_key}"
    return sse_endpoint(request, channel)


@router.get("/{project_key}")
async def list_notifications(
    project_key: str,
    unread_only: bool = False,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return persisted notifications for a project, newest first."""
    stmt = (
        select(Notification)
        .where(Notification.project_key == project_key)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read == False)  # noqa: E712

    result = await db.execute(stmt)
    notifications = result.scalars().all()

    return [
        {
            "id": n.id,
            "type": n.type,
            "title": n.title,
            "body": n.body,
            "severity": n.severity,
            "issue_key": n.issue_key,
            "is_read": n.is_read,
            "jira_comment_posted": n.jira_comment_posted,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifications
    ]


@router.post("/{notification_id}/read")
async def mark_as_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a single notification as read."""
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    notif = result.scalar_one_or_none()
    if notif is None:
        raise HTTPException(404, "Notification not found")

    notif.is_read = True
    await db.commit()
    return {"success": True}


@router.post("/{project_key}/read-all")
async def mark_all_read(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark all unread notifications for a project as read."""
    await db.execute(
        update(Notification)
        .where(
            Notification.project_key == project_key,
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"success": True}
