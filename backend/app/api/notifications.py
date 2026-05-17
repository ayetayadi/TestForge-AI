"""
Notifications API

Endpoints:
  GET /notifications/stream/{project_key} — SSE real-time stream
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.streaming.sse_manager import sse_endpoint
from sqlalchemy import select

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
    return sse_endpoint(request, channel, replay=False)
