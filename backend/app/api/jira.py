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
from app.services.jira_client import ATLASSIAN_API_URL

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
@router.get("/projects/", include_in_schema=False)
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


@router.get("/debug/fields/{project_key}")
async def debug_fields(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Debug: Affiche tous les champs d'une story du projet."""
    manager = JiraSessionManager(db)
    conn = await manager.get_connection(user.id)
    client = await manager.get_client(conn)
    
    try:
        # Récupérer une seule story du projet
        jql = f'project="{project_key}" AND issuetype="Story"'
        url = f"{ATLASSIAN_API_URL}/ex/jira/{client.cloud_id}/rest/api/3/search/jql"
        
        body = {
            "jql": jql,
            "fields": ["*all"],
            "maxResults": 1
        }
        
        data = await client._request("POST", url, json=body)
        issues = data.get("issues", [])
        
        if not issues:
            return {"error": "No story found"}
        
        fields = issues[0].get("fields", {})
        
        # Chercher les champs qui pourraient contenir MoSCoW
        result = {
            "story_key": issues[0].get("key"),
            "moscow_candidates": [],
            "all_custom_fields": {}
        }
        
        for key, value in fields.items():
            if key.startswith("customfield_"):
                value_str = str(value)[:150]
                result["all_custom_fields"][key] = value_str
                
                # Chercher des valeurs MoSCoW potentielles
                if any(word in value_str.lower() for word in ["must", "should", "could", "won't", "moscow"]):
                    result["moscow_candidates"].append({
                        "field": key,
                        "value": value_str
                    })
        
        return result
        
    except Exception as e:
        return {"error": str(e)}
    
# =========================
# 6. EPICS
# =========================
@router.get("/epics/{project_key}")
async def epics(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    manager = JiraSessionManager(db)
    conn    = await manager.get_connection(user.id)
    client  = await manager.get_client(conn)
    return await client.get_epics(project_key)


# =========================
# 7. SPRINTS
# =========================
@router.get("/sprints/{project_key}")
async def sprints(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    manager = JiraSessionManager(db)
    conn    = await manager.get_connection(user.id)
    client  = await manager.get_client(conn)
    return await client.get_sprints(project_key)


# =========================
# 8. DISCONNECT
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
