from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.jira_project import JiraProject
from app.models.user_story import UserStory
from app.repositories.jira_connection_repository import get_default_connection


async def get_all_projects(db: AsyncSession):
    result = await db.execute(select(JiraProject))
    return result.scalars().all()


async def get_project_by_key(db: AsyncSession, project_key: str):
    result = await db.execute(
        select(JiraProject).where(JiraProject.project_key == project_key)
    )
    return result.scalar_one_or_none()


async def create_project(db: AsyncSession, project_key: str, project_name: str):
    connection = await get_default_connection(db)

    if not connection:
        raise Exception("No active Jira connection found")

    project = JiraProject(
        project_key=project_key,
        project_name=project_name,
        jira_connection_id=connection.id
    )

    db.add(project)
    await db.commit()
    await db.refresh(project)

    return project


async def get_projects_with_story_count(db: AsyncSession):
    result = await db.execute(
        select(
            JiraProject.id,
            JiraProject.project_key,
            JiraProject.project_name,
            func.count(UserStory.id).label("story_count")
        )
        .outerjoin(UserStory, UserStory.jira_project_id == JiraProject.id)
        .group_by(JiraProject.id)
    )
    return result.all()