from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.user_story_repository import get_user_story_by_id
from app.repositories.user_story_version_repository import (
    get_latest_version,
    get_selected_version,
    get_versions_by_story_id,
)
from app.models.enums import StoryDecision

async def get_final_details(db: AsyncSession, user_story_id: str):
    user_story = await get_user_story_by_id(db, user_story_id)

    if not user_story:
        raise ValueError("User story not found")

    selected = await get_selected_version(db, user_story_id)
    latest = await get_latest_version(db, user_story_id)
    versions = await get_versions_by_story_id(db, user_story_id)

    return {
        "issue_key": user_story.issue_key,
        "project_id": user_story.project_id,
        "selected_version": selected,
        "latest_version": latest,
        "versions": versions,
    }