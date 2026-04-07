from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user_story import UserStory


async def get_all_stories(db: AsyncSession):
    result = await db.execute(select(UserStory))
    return result.scalars().all()


async def get_story_by_issue_key(db: AsyncSession, issue_key):
    result = await db.execute(
        select(UserStory).where(UserStory.issue_key == issue_key)
    )
    return result.scalar_one_or_none()


async def get_stories_by_project_id(db: AsyncSession, project_id):
    result = await db.execute(
        select(UserStory).where(UserStory.jira_project_id == project_id)
    )
    return result.scalars().all()


async def story_exists(db: AsyncSession, issue_key):
    result = await db.execute(
        select(UserStory).where(UserStory.issue_key == issue_key)
    )
    return result.scalar_one_or_none() is not None


async def create_story(db: AsyncSession, data):
    story = UserStory(**data)
    db.add(story)
    return story