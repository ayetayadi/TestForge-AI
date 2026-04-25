from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.models.user import User

from app.repositories.project_repository import (
    create_project,
    delete_project_by_id,
    get_project_by_key,
    get_projects_with_story_count,
)

from app.services.jira_session_manager import JiraSessionManager
from app.services.user_story_service import import_project_stories

async def get_all_projects(db: AsyncSession):
    projects = await get_projects_with_story_count(db)
    return [
        {
            "id": p.id,
            "project_key": p.project_key,
            "project_name": p.project_name,
            "story_count": p.story_count,
        }
        for p in projects
    ]

async def import_project_by_key(
    db: AsyncSession,
    project_key: str,
    current_user: User,
) -> dict:

    try:
        manager = JiraSessionManager(db)
        conn    = await manager.get_connection(current_user.id)
        client  = await manager.get_client(conn)

        # =========================
        # FETCH PROJECTS
        # =========================
        jira_projects = await client.get_projects()

        jira_project = {p["key"]: p for p in jira_projects}.get(project_key)

        if not jira_project:
            raise HTTPException(404, "Project not found")

        # =========================
        # CREATE OR GET PROJECT
        # =========================
        project = await get_project_by_key(db, project_key)

        if not project:
            project = await create_project(
                db,
                jira_connection_id=conn.id,
                project_key=jira_project["key"],
                project_name=jira_project["name"],
            )

        # =========================
        # FETCH STORIES
        # =========================
        jira_issues = await client.get_stories(project_key)

        # =========================
        # IMPORT STORIES
        # =========================
        import_result = await import_project_stories(db, project, jira_issues)

        await db.commit()

        return {
            "message": "Import successful",
            "project": {
                "key": project.project_key,
                "name": project.project_name,
            },
            "result": import_result,
        }

    except Exception:
        await db.rollback()
        raise
    

async def delete_project(db: AsyncSession, project_id: str):
    deleted = await delete_project_by_id(db, project_id)

    if not deleted:
        raise ValueError("Project not found")

    await db.commit()

    return {"message": "Project deleted successfully"}
