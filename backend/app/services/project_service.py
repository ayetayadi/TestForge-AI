from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.repositories.project_repository import (
    get_project_by_key,
    create_project,
    get_projects_with_story_count
)
from app.services.story_service import import_project_stories
from app.clients.jira_client import fetch_projects


async def get_projects(db: AsyncSession):
    projects = await get_projects_with_story_count(db)

    return [
        {
            "id": p.id,
            "project_key": p.project_key,
            "name": p.project_name,
            "story_count": p.story_count
        }
        for p in projects
    ]


async def get_jira_projects():
    try:
        return fetch_projects()
    except Exception as e:
        print("🔥 JIRA ERROR:", str(e))   # 👈 IMPORTANT
        raise HTTPException(status_code=502, detail=str(e))


async def import_project_by_key(db: AsyncSession, project_key: str):

    project = await get_project_by_key(db, project_key)

    if not project:
        jira_projects = fetch_projects()

        jira_project = next(
            (p for p in jira_projects if p.get("key") == project_key),
            None
        )

        if not jira_project:
            raise HTTPException(status_code=404, detail="Project not found in Jira")

        project = await create_project(
            db,
            project_key=jira_project.get("key"),
            project_name=jira_project.get("name")
        )

    result = await import_project_stories(db, project)

    return {
        "message": "User stories imported successfully",
        "project": {
            "key": project.project_key,
            "name": project.project_name
        },
        "result": result
    }