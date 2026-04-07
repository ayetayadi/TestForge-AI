from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.jira_connection import JiraConnection
from app.models.user import User

from app.repositories.project_repository import (
    create_project,
    get_project_by_key,
    get_projects_with_story_count,
)

from app.services.jira_service import (
    fetch_jira_projects,
    fetch_user_stories,
)

from app.services.stories_service import import_project_stories


# =========================
# GET PROJECTS
# =========================
async def get_projects(db: AsyncSession):
    projects = await get_projects_with_story_count(db)

    return [
        {
            "id": p.id,
            "project_key": p.project_key,
            "name": p.project_name,
            "story_count": p.story_count,
        }
        for p in projects
    ]


# =========================
# IMPORT PROJECT
# =========================
async def import_project_by_key(
    db: AsyncSession,
    project_key: str,
    current_user: User,
) -> dict:
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.user_id == current_user.id)
    )
    jira_connection = result.scalar_one_or_none()

    if not jira_connection or not jira_connection.is_active:
        raise HTTPException(status_code=400, detail="Jira not connected")

    if not jira_connection.access_token:
        raise HTTPException(status_code=400, detail="Missing token")

    if not jira_connection.cloud_id:
        raise HTTPException(status_code=400, detail="Missing cloud_id")

    access_token = await _ensure_valid_token(jira_connection)

    jira_projects = await fetch_jira_projects(
        access_token,
        jira_connection.cloud_id,
    )

    jira_project = {p["key"]: p for p in jira_projects}.get(project_key)

    if not jira_project:
        raise HTTPException(status_code=404, detail="Project not found")

    project = await get_project_by_key(db, project_key)

    if not project:
        project = await create_project(
            db,
            project_key=jira_project["key"],
            project_name=jira_project["name"],
        )

    jira_issues = await fetch_user_stories(
        access_token,
        jira_connection.cloud_id,
        project_key,
    )

    result = await import_project_stories(db, project, jira_issues)

    return {
        "message": "Import successful",
        "project": {
            "key": project.project_key,
            "name": project.project_name,
        },
        "result": {
            "imported": result.get("imported", 0),
            "skipped": result.get("skipped", 0),
            "total": len(jira_issues),
        },
    }


async def _ensure_valid_token(jira_connection):
    """Vérifie et rafraîchit le token si nécessaire"""
    from datetime import datetime
    
    # Si le token expire dans moins de 5 minutes, on le rafraîchit
    if jira_connection.token_expires_at and jira_connection.refresh_token:
        if datetime.utcnow() >= jira_connection.token_expires_at:
            from app.services.jira_service import refresh_access_token
            
            try:
                new_tokens = await refresh_access_token(jira_connection.refresh_token)
                
                # Mettre à jour la connexion
                jira_connection.access_token = new_tokens["access_token"]
                jira_connection.refresh_token = new_tokens.get("refresh_token", jira_connection.refresh_token)
                
                from datetime import timedelta
                jira_connection.token_expires_at = datetime.utcnow() + timedelta(seconds=new_tokens["expires_in"])
                
                return new_tokens["access_token"]
            except Exception as e:
                raise HTTPException(status_code=401, detail=f"Token refresh failed: {str(e)}")
    
    return jira_connection.access_token