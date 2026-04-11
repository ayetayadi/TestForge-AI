from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.user_story import UserStory
from datetime import datetime


# =========================
# GET ALL
# =========================
async def get_all_user_stories(db: AsyncSession):
    result = await db.execute(select(UserStory))
    return result.scalars().all()


# =========================
# GET BY PROJECT
# =========================
async def get_user_stories_by_project_id(db: AsyncSession, project_id: str):
    result = await db.execute(
        select(UserStory).where(UserStory.project_id == project_id)
    )
    return result.scalars().all()


async def count_user_stories_by_project(db: AsyncSession, project_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(UserStory).where(
            UserStory.project_id == project_id
        )
    )
    return result.scalar_one()


# =========================
# GET BY IDS
# =========================
async def get_user_stories_by_ids(db: AsyncSession, ids: list[str]):
    if not ids:
        return []

    result = await db.execute(
        select(UserStory).where(UserStory.id.in_(ids))
    )
    return result.scalars().all()


async def count_user_stories_by_ids(db: AsyncSession, ids: list[str]) -> int:
    if not ids:
        return 0

    result = await db.execute(
        select(func.count()).select_from(UserStory).where(
            UserStory.id.in_(ids)
        )
    )
    return result.scalar_one()


# =========================
# GET SINGLE
# =========================
async def get_user_story_by_id(db: AsyncSession, user_story_id: str):
    result = await db.execute(
        select(UserStory).where(UserStory.id == user_story_id)
    )
    return result.scalar_one_or_none()


async def get_user_story_by_issue_key(db: AsyncSession, issue_key: str):
    result = await db.execute(
        select(UserStory).where(UserStory.issue_key == issue_key)
    )
    return result.scalar_one_or_none()


# =========================
# CREATE
# =========================
async def create_user_story(
    db: AsyncSession,
    issue_key: str,
    project_id: str,
    title: str,
    description: str | None = None,
    acceptance_criteria: list | None = None,
    issue_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    story_points: float | None = None,
    assignee: str | None = None,
    reporter: str | None = None,
    epic_key: str | None = None,
    sprint: str | None = None,
    labels: list | None = None,
    components: list | None = None,
    fix_version: str | None = None,
    jira_created_at: datetime | None = None,
    jira_updated_at: datetime | None = None,
):
    user_story = UserStory(
    issue_key=issue_key,
    project_id=project_id,
    title=title,
    description=description,
    acceptance_criteria=acceptance_criteria or [],
    issue_type=issue_type,
    jira_status=status,
    priority=priority,
    story_points=story_points,
    assignee=assignee,
    reporter=reporter,
    epic_key=epic_key,
    sprint=sprint,
    labels=labels or [],
    components=components or [],
    fix_version=fix_version,
    jira_created_at=jira_created_at,
    jira_updated_at=jira_updated_at,
    )

    db.add(user_story)
    await db.flush()

    return user_story
