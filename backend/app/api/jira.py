import uuid
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.jira_connection import JiraConnection
from app.models.user import User
from app.schemas.jira_schema import JiraProject, JiraStatusResponse
from app.services.jira_service import (
    exchange_code_for_token,
    fetch_jira_projects,
    fetch_user_stories,
    get_cloud_id,
    get_oauth_url,
)

router = APIRouter(prefix="/jira", tags=["Jira"])


@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    state = f"{user.id}:{secrets.token_urlsafe(16)}"
    url = get_oauth_url(state)
    return {"url": url}


@router.get("/callback")
async def jira_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        user_id = state.split(":")[0]

        token_data = await exchange_code_for_token(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")

        cloud_id = await get_cloud_id(access_token)

        result = await db.execute(
            select(JiraConnection).where(JiraConnection.user_id == user_id)
        )
        cred = result.scalar_one_or_none()

        if cred:
            cred.jira_url = "https://api.atlassian.com"
            cred.jira_email = ""
            cred.cloud_id = cloud_id
            cred.is_active = True
            cred.access_token = access_token
            cred.refresh_token = refresh_token
        else:
            cred = JiraConnection(
                id=str(uuid.uuid4()),
                user_id=user_id,
                jira_url="https://api.atlassian.com",
                jira_email="",
                cloud_id=cloud_id,
                is_active=True,
                access_token=access_token,
                refresh_token=refresh_token,
            )
            db.add(cred)

        await db.commit()

        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/dashboard/jira?connected=true"
        )

    except Exception as e:
        await db.rollback()
        print("JIRA CALLBACK ERROR:", repr(e))
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

    if not cred.access_token:
        raise HTTPException(status_code=400, detail="Missing Jira access token")

    if not cred.cloud_id:
        raise HTTPException(status_code=400, detail="Missing Jira cloud_id")

    return await fetch_jira_projects(cred.access_token, cred.cloud_id)


@router.get("/stories/{project_key}")
async def get_jira_stories(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.user_id == current_user.id)
    )
    jira_connection = result.scalar_one_or_none()

    if not jira_connection or not jira_connection.is_active:
        raise HTTPException(status_code=400, detail="Jira account not connected")

    if not jira_connection.access_token:
        raise HTTPException(status_code=400, detail="Missing Jira access token")

    if not jira_connection.cloud_id:
        raise HTTPException(status_code=400, detail="Missing Jira cloud_id")

    try:
        return await fetch_user_stories(
            jira_connection.access_token,
            jira_connection.cloud_id,
            project_key,
        )
    except Exception as e:
        print("GET STORIES ERROR:", str(e))
        raise HTTPException(status_code=500, detail=str(e))


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