from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user_story_version import UserStoryVersion


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

async def get_versions_by_story_id(db, story_id: str):
    result = await db.execute(
        select(UserStoryVersion).where(
            UserStoryVersion.user_story_id == story_id
        )
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
        select(UserStoryVersion).where(
            UserStoryVersion.user_story_id == story_id,
            UserStoryVersion.is_selected == True
        )
    )
    return result.scalar_one_or_none()


async def get_latest_version(db: AsyncSession, story_id: str):
    result = await db.execute(
        select(UserStoryVersion)
        .where(UserStoryVersion.user_story_id == story_id)
        .order_by(desc(UserStoryVersion.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def reset_selected_versions(db: AsyncSession, story_id: str):
    result = await db.execute(
        select(UserStoryVersion).where(
            UserStoryVersion.user_story_id == story_id
        )
    )
    versions = result.scalars().all()

    for v in versions:
        v.is_selected = False


# CRITICAL FIX
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
    duration
):
    # 1️⃣ éviter doublon par job
    existing = await db.execute(
        select(UserStoryVersion).where(
            UserStoryVersion.job_id == job_id
        )
    )
    existing_version = existing.scalar_one_or_none()

    if existing_version:
        return existing_version

    # 2️⃣ éviter duplication réelle (même contenu)
    duplicate = await db.execute(
        select(UserStoryVersion).where(
            UserStoryVersion.user_story_id == user_story_id,
            UserStoryVersion.improved_story == improved_story
        )
    )
    duplicate_version = duplicate.scalar_one_or_none()

    if duplicate_version:
        return duplicate_version

    # 3️⃣ créer version
    version = UserStoryVersion(
        user_story_id=user_story_id,
        job_id=job_id,
        improved_story=improved_story,
        acceptance_criteria=acceptance_criteria,
        initial_score=initial_score,
        final_score=final_score,
        iteration=iteration,
        llm_calls=llm_calls,
        duration=duration,
    )

    db.add(version)

    # ⚠️ flush pour récupérer ID sans commit global
    await db.flush()

    return version