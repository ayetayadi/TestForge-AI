from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from app.models.jira_project import JiraProject
from app.models.user_story import UserStory


# =========================
# GET ALL
# =========================
async def get_all_projects(db: AsyncSession):
    result = await db.execute(select(JiraProject))
    return result.scalars().all()


# =========================
# GET BY ID
# =========================
async def get_project_by_id(
    db: AsyncSession,
    project_id: str
) -> JiraProject | None:
    result = await db.execute(
        select(JiraProject).where(JiraProject.id == project_id)
    )
    return result.scalar_one_or_none()


# =========================
# GET BY KEY (IMPORTANT)
# =========================
async def get_project_by_key(
    db: AsyncSession,
    project_key: str
) -> JiraProject | None:
    result = await db.execute(
        select(JiraProject).where(JiraProject.project_key == project_key)
    )
    return result.scalar_one_or_none()


# =========================
# CREATE PROJECT
# =========================
async def create_project(
    db: AsyncSession,
    jira_connection_id: str,
    project_key: str,
    project_name: str
) -> JiraProject:
    project = JiraProject(
        jira_connection_id=jira_connection_id,
        project_key=project_key,
        project_name=project_name
    )

    db.add(project)

    # flush pour récupérer l'id sans commit immédiat
    await db.flush()

    return project


# =========================
# PROJECTS + STORY COUNT
# =========================
async def get_projects_with_story_count(db: AsyncSession):
    result = await db.execute(
        select(
            JiraProject.id,
            JiraProject.project_key,
            JiraProject.project_name,
            func.count(UserStory.id).label("story_count")
        )
        .outerjoin(UserStory, UserStory.project_id == JiraProject.id)
        .group_by(
            JiraProject.id,
            JiraProject.project_key,
            JiraProject.project_name
        )
    )
    return result.all()


async def delete_project_by_id(db: AsyncSession, project_id: str) -> bool:
    result = await db.execute(
        select(JiraProject).where(JiraProject.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        return False

    await db.delete(project)
    return True

# =========================
# DELETE
# =========================
async def delete_project_by_id(
    db: AsyncSession,
    project_id: str
) -> bool:
    result = await db.execute(
        select(JiraProject).where(JiraProject.id == project_id)
    )
    project = result.scalar_one_or_none()

    if not project:
        return False

    await db.delete(project)
    await db.commit()

    return True