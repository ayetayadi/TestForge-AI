from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.repositories.project_repository import (
    get_project_by_key,
    create_project
)
from app.services.story_service import import_project_stories
from app.clients.jira_client import fetch_projects


def get_projects(db: Session):
    from app.repositories.project_repository import get_projects_with_story_count

    projects = get_projects_with_story_count(db)

    return [
        {
            "id": p.id,
            "project_key": p.project_key,
            "name": p.project_name,
            "story_count": p.story_count
        }
        for p in projects
    ]


def get_jira_projects():
    try:
        return fetch_projects()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


def import_project_by_key(db: Session, project_key: str):

    # 1. check DB
    project = get_project_by_key(db, project_key)

    # 2. create if not exists
    if not project:
        jira_projects = fetch_projects()
        jira_project = next(
            (p for p in jira_projects if p.get("key") == project_key),
            None
        )

        if not jira_project:
            raise HTTPException(status_code=404, detail="Project not found in Jira")

        project = create_project(
            db,
            project_key=jira_project.get("key"),
            project_name=jira_project.get("name")
        )

    # 3. import stories
    result = import_project_stories(db, project)

    return {
        "message": "User stories imported successfully",
        "project": {
            "key": project.project_key,
            "name": project.project_name
        },
        "result": result
    }