from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user_story_version import UserStoryVersion
from app.models.enums import StoryDecision, AgentStatus
from datetime import datetime
from typing import List, Optional


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


async def get_versions_by_story_id(
    db: AsyncSession, 
    story_id: str,
    limit: int = None
) -> List[UserStoryVersion]:
    query = (
        select(UserStoryVersion)
        .where(UserStoryVersion.user_story_id == story_id)
        .order_by(UserStoryVersion.started_at.desc())  # ← plus récent d'abord
    )
    
    if limit:
        query = query.limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()


async def get_versions_by_story_ids(
    db: AsyncSession, 
    story_ids: list[str]
) -> List[UserStoryVersion]:
    if not story_ids:
        return []

    result = await db.execute(
        select(UserStoryVersion)
        .where(UserStoryVersion.user_story_id.in_(story_ids))
        .order_by(
            UserStoryVersion.user_story_id, 
            desc(UserStoryVersion.started_at)  # ← utiliser started_at
        )
    )
    return result.scalars().all()


async def get_selected_version(
    db: AsyncSession, 
    story_id: str
) -> UserStoryVersion | None:
    """Récupère la version approuvée"""
    result = await db.execute(
        select(UserStoryVersion)
        .where(
            UserStoryVersion.user_story_id == story_id,
            UserStoryVersion.decision_status == StoryDecision.APPROVED
        )
        .order_by(desc(UserStoryVersion.started_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_version(
    db: AsyncSession, 
    story_id: str
) -> UserStoryVersion | None:
    """Récupère la version la plus récente"""
    result = await db.execute(
        select(UserStoryVersion)
        .where(UserStoryVersion.user_story_id == story_id)
        .order_by(desc(UserStoryVersion.started_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_best_version(
    db: AsyncSession, 
    user_story_id: str
) -> UserStoryVersion | None:
    """Récupère la version avec le meilleur score"""
    result = await db.execute(
        select(UserStoryVersion)
        .where(UserStoryVersion.user_story_id == user_story_id)
        .order_by(desc(UserStoryVersion.final_score))
        .limit(1)
    )
    return result.scalars().first()


async def get_processing_versions(
    db: AsyncSession
) -> List[UserStoryVersion]:
    """Récupère toutes les versions en cours de traitement"""
    result = await db.execute(
        select(UserStoryVersion)
        .where(UserStoryVersion.agent_status == AgentStatus.PROCESSING)
        .order_by(UserStoryVersion.started_at)
    )
    return result.scalars().all()


async def create_version(
    db: AsyncSession,
    user_story_id: str,
    improved_story: str,
    acceptance_criteria: List[str],
    initial_score: float,
    final_score: float,
    llm_calls: int,
    duration: float,
    model_used: str,
    prompt_tokens: int,
    completion_tokens: int,
    testability_score: float,
    is_testable: bool,
    testability_issues: List[str],
    agent_status: AgentStatus,
    started_at: datetime,
    completed_at: datetime = None,  # ← Optional
    decision_status: StoryDecision = StoryDecision.PENDING,  # ← Default PENDING

) -> UserStoryVersion:
    """Crée une nouvelle version"""
    
    version = UserStoryVersion(
        user_story_id=user_story_id,
        improved_story=improved_story,
        generated_acceptance_criteria=acceptance_criteria,
        initial_score=initial_score,
        final_score=final_score,
        llm_calls=llm_calls,
        duration=duration,
        model_used=model_used,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        testability_score=testability_score,
        is_testable=is_testable,
        testability_issues=testability_issues,
        agent_status=agent_status,
        started_at=started_at,
        completed_at=completed_at,
        decision_status=decision_status,
    )

    db.add(version)
    await db.flush()
    # Pas de commit ici, laisser le caller gérer la transaction

    return version


async def update_version_status(
    db: AsyncSession,
    version_id: str,
    agent_status: AgentStatus,
    completed_at: datetime = None,
    error: str = None
) -> UserStoryVersion | None:
    """Met à jour le statut d'une version"""
    version = await get_version_by_id(db, version_id)
    if not version:
        return None
    
    version.agent_status = agent_status
    
    if completed_at:
        version.completed_at = completed_at
    elif agent_status in [AgentStatus.COMPLETED, AgentStatus.FAILED]:
        version.completed_at = datetime.utcnow()
    
    if error:
        version.error = error
    
    await db.flush()
    return version


async def update_version_decision(
    db: AsyncSession,
    version_id: str,
    decision_status: StoryDecision
) -> UserStoryVersion | None:
    """Met à jour la décision d'une version"""
    version = await get_version_by_id(db, version_id)
    if not version:
        return None
    
    version.decision_status = decision_status
    await db.flush()
    return version