import uuid
import secrets

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
    fetch_user_stories,
)

router = APIRouter(prefix="/jira", tags=["Jira"])


@router.get("/auth-url")
async def get_auth_url(user: User = Depends(get_current_user)):
    state = f"{user.id}:{secrets.token_urlsafe(16)}"
    url = get_oauth_url(state)
    return {"url": url}


import uuid
import secrets

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
    fetch_user_stories,
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
        print("[JIRA CALLBACK] user_id from state:", user_id)

        token_data = await exchange_code_for_token(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        print("[JIRA CALLBACK] token exchange OK")

        cloud_id = await get_cloud_id(access_token)
        print("[JIRA CALLBACK] cloud_id:", cloud_id)

        result = await db.execute(
            select(JiraConnection).where(JiraConnection.user_id == user_id)
        )
        cred = result.scalar_one_or_none()
        print("[JIRA CALLBACK] existing connection:", cred is not None)

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
            )
            cred.access_token = access_token
            cred.refresh_token = refresh_token
            db.add(cred)
            print("[JIRA CALLBACK] new connection added to session")

        await db.commit()
        print("[JIRA CALLBACK] commit OK")

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

    try:
        projects = await fetch_jira_projects(cred.access_token, cred.cloud_id)
        return projects
    except Exception as e:
        print("GET PROJECTS ERROR:", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch Jira projects")


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
        stories = await fetch_user_stories(
            jira_connection.access_token,
            jira_connection.cloud_id,
            project_key,
        )
        return stories
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