from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.user_story_repository import get_user_story_by_id
from app.repositories.user_story_version_repository import (
    get_selected_version,
    get_latest_version,
)


async def get_final_details(db: AsyncSession, user_story_id: str):
    user_story = await get_user_story_by_id(db, user_story_id)

    if not user_story:
        raise ValueError("User story not found")

    # priorité : version sélectionnée
    version = await get_selected_version(db, user_story_id)

    # fallback : dernière version
    if not version:
        version = await get_latest_version(db, user_story_id)

    if not version:
        raise ValueError("No version found")

    return {
        "id": version.id,

        # ✅ vient de UserStory
        "issue_key": user_story.issue_key,
        "project_id": user_story.project_id,

        # ✅ vient de Version
        "improved_story": version.improved_story,
        "acceptance_criteria": version.acceptance_criteria,

        "initial_score": version.initial_score,
        "final_score": version.final_score,
        "iteration": version.iteration,
        "llm_calls": version.llm_calls,
        "duration": version.duration,

        "is_selected": version.is_selected,

        # ✅ décision portée par UserStory
        "decision_status": user_story.decision_status.value,
    }
