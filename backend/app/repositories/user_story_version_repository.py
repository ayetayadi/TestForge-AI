from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user_story_version import UserStoryVersion
from app.models.enums import StoryDecision

async def get_version_by_id(
    db: AsyncSession,
    version_id: str
) -> UserStoryVersion | None:
    result = await db.execute(
        select(UserStoryVersion).where(
            UserStoryVersion.id == version_id
        )
    )
    return result.scalar_one_or_none()

async def get_versions_by_story_id(db: AsyncSession, story_id: str):
    result = await db.execute(
        select(UserStoryVersion)
        .where(UserStoryVersion.user_story_id == story_id)
        .order_by(UserStoryVersion.created_at.asc())
    )
    return result.scalars().all()

async def get_versions_by_story_ids(db: AsyncSession, story_ids: list[str]):
    if not story_ids:
        return []

    result = await db.execute(
        select(UserStoryVersion)
        .where(UserStoryVersion.user_story_id.in_(story_ids))
        .order_by(UserStoryVersion.user_story_id, desc(UserStoryVersion.created_at))
    )
    return result.scalars().all()

async def get_selected_version(db: AsyncSession, story_id: str):
    result = await db.execute(
        select(UserStoryVersion)
        .where(
            UserStoryVersion.user_story_id == story_id,
            UserStoryVersion.decision_status == StoryDecision.APPROVED
        )
        .order_by(desc(UserStoryVersion.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()

async def get_latest_version(db: AsyncSession, story_id: str):
    result = await db.execute(
        select(UserStoryVersion)
        .where(UserStoryVersion.user_story_id == story_id)
        .order_by(
            desc(UserStoryVersion.iteration),
            desc(UserStoryVersion.created_at)
        )
        .limit(1)
    )
    return result.scalar_one_or_none()

async def get_best_version(db, user_story_id: str):
    result = await db.execute(
        select(UserStoryVersion)
        .where(UserStoryVersion.user_story_id == user_story_id)
        .order_by(desc(UserStoryVersion.final_score))
    )
    return result.scalars().first()

async def create_version(
    db: AsyncSession,
    user_story_id: str,
    job_id: str,
    improved_story: str,
    acceptance_criteria,
    initial_score,
    final_score,
    iteration,
    llm_calls,
    duration,
    model_used,
    prompt_tokens,
    completion_tokens
):


    # 2 créer version
    version = UserStoryVersion(
        user_story_id=user_story_id,
        job_id=job_id,
        improved_story=improved_story,
        generated_acceptance_criteria=acceptance_criteria,
        initial_score=initial_score,
        final_score=final_score,
        iteration=iteration,
        llm_calls=llm_calls,
        duration=duration,
        model_used=model_used,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,

    )

    db.add(version)

    await db.flush()

    return version