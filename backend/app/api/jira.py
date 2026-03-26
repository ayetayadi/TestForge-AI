from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.config import settings
from app.models.user import User
from app.models.jira_connection import JiraConnection
from app.schemas.jira import JiraStatusResponse, JiraProject
from app.api.deps import get_current_user
from app.services.jira_service import (
    get_oauth_url,
    exchange_code_for_token,
    get_cloud_id,
    fetch_jira_projects,
)
import uuid
import secrets

router = APIRouter(prefix="/jira", tags=["Jira"])


@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    """Returns the Atlassian OAuth URL for the frontend to redirect to."""
    state = f"{user.id}:{secrets.token_urlsafe(16)}"
    url = get_oauth_url(state)
    return {"url": url}


@router.get("/callback")
async def jira_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Atlassian redirects here after user accepts. Saves token and redirects to frontend."""
    try:
        # Extract user_id from state
        user_id = state.split(":")[0]

        # Exchange code for tokens
        token_data = await exchange_code_for_token(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")

        # Get cloud ID
        cloud_id = await get_cloud_id(access_token)

        # Save to DB (upsert)
        result = await db.execute(
            select(JiraConnection).where(JiraConnection.user_id == user_id)
        )
        cred = result.scalar_one_or_none()

        if cred:
            cred.jira_api_token = access_token
            cred.refresh_token = refresh_token
            cred.cloud_id = cloud_id
            cred.is_active = True
        else:
            cred = JiraConnection(
                id=str(uuid.uuid4()),
                user_id=user_id,
                jira_url="https://api.atlassian.com",
                jira_email="",
                jira_api_token=access_token,
                refresh_token=refresh_token,
                cloud_id=cloud_id,
                is_active=True,
            )
            db.add(cred)

        await db.commit()

        # Redirect back to Angular
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard/jira?connected=true"
        )

    except Exception as e:
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard/jira?error=connection_failed"
        )


@router.get("/status", response_model=JiraStatusResponse)
async def jira_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.user_id == user.id)
    )
    cred = result.scalar_one_or_none()
    if not cred or not cred.is_active:
        return JiraStatusResponse(connected=False)
    return JiraStatusResponse(
        connected=True,
        jira_url=cred.jira_url,
        jira_email=cred.jira_email,
    )


@router.get("/projects", response_model=list[JiraProject])
async def get_projects(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.user_id == user.id)
    )
    cred = result.scalar_one_or_none()
    if not cred or not cred.is_active:
        raise HTTPException(status_code=404, detail="Jira not connected")

    projects = await fetch_jira_projects(cred.jira_api_token, cred.cloud_id)
    return projects


@router.delete("/disconnect", status_code=204)
async def disconnect_jira(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.user_id == user.id)
    )
    cred = result.scalar_one_or_none()
    if cred:
        await db.delete(cred)
        await db.commit()