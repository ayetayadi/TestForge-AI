import uuid
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.models.jira_connection import JiraConnection

from app.services.jira_service import (
    get_oauth_url,
    exchange_code_for_token,
    get_cloud_id,
)
from app.services.jira_session_manager import JiraSessionManager

router = APIRouter(prefix="/jira", tags=["Jira"])


# =========================
# 1. AUTH URL
# =========================
@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    state = f"{user.id}:{secrets.token_urlsafe(16)}"
    return {"url": get_oauth_url(state)}


# =========================
# 2. CALLBACK
# =========================
@router.get("/callback")
async def jira_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    user_id = state.split(":")[0]

    token_data = await exchange_code_for_token(code)

    access_token  = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    expires_in    = token_data.get("expires_in", 3600)
    token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    cloud_id = await get_cloud_id(access_token)

    result = await db.execute(
        select(JiraConnection).where(JiraConnection.user_id == user_id)
    )
    conn = result.scalar_one_or_none()

    if conn:
        conn.access_token    = access_token
        conn.refresh_token   = refresh_token
        conn.cloud_id        = cloud_id
        conn.token_expires_at = token_expires_at
        conn.is_active       = True
    else:
        conn = JiraConnection(
            id=str(uuid.uuid4()),
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            cloud_id=cloud_id,
            token_expires_at=token_expires_at,
            is_active=True,
        )
        db.add(conn)

    await db.commit()

    return RedirectResponse(
        url=f"{settings.FRONTEND_URL}/dashboard/jira?connected=true"
    )


# =========================
# 3. STATUS
# =========================
@router.get("/status")
async def status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.user_id == user.id)
    )
    conn = result.scalar_one_or_none()

    return {
        "connected": bool(conn and conn.is_active),
        "jira_url":  conn.jira_url if conn else None,
    }


# =========================
# 4. PROJECTS
# =========================
@router.get("/projects")
async def projects(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    manager = JiraSessionManager(db)
    conn    = await manager.get_connection(user.id)
    client  = await manager.get_client(conn)
    return await client.get_projects()


# =========================
# 5. STORIES  (preview only — for the settings UI)
# =========================
@router.get("/stories/{project_key}")
async def stories(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    manager = JiraSessionManager(db)
    conn    = await manager.get_connection(user.id)
    client  = await manager.get_client(conn)
    return await client.get_stories_preview(project_key)


# =========================
# 6. DISCONNECT
# =========================
@router.delete("/disconnect", status_code=204)
async def disconnect(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.user_id == user.id)
    )
    conn = result.scalar_one_or_none()

    if conn:
        await db.delete(conn)
        await db.commit()
