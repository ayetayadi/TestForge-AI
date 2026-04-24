from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user_story_version import UserStoryVersion
from app.models.enums import StoryDecision, WorkflowStatus
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
        .where(UserStoryVersion.workflow_status == WorkflowStatus.PROCESSING)
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
    testability_score: float,
    is_testable: bool,
    testability_issues: List[str],
    workflow_status: WorkflowStatus,
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
        testability_score=testability_score,
        is_testable=is_testable,
        testability_issues=testability_issues,
        workflow_status=workflow_status,
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
    workflow_status: WorkflowStatus,
    completed_at: datetime = None,
    error: str = None
) -> UserStoryVersion | None:
    """Met à jour le statut d'une version"""
    version = await get_version_by_id(db, version_id)
    if not version:
        return None
    
    version.workflow_status = workflow_status
    
    if completed_at:
        version.completed_at = completed_at
    elif workflow_status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]:
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

async def update_version_content(
    db: AsyncSession,
    version_id: str,
    improved_story: str,
    acceptance_criteria: List[str]
) -> UserStoryVersion | None:
    """
    Met à jour le contenu d'une version existante.
    Marque la version comme 'customized' lors de la première modification.
    """
    version = await get_version_by_id(db, version_id)
    if not version:
        return None
    
    # Vérifier qu'on peut modifier (pas approved)
    if version.decision_status == StoryDecision.APPROVED:
        raise PermissionError(f"Cannot modify approved version {version_id}")
    
    # Si c'est la première modification, marquer comme personnalisée
    if not version.is_customized:
        version.is_customized = True
        version.customized_at = datetime.utcnow()
    
    # Mettre à jour le contenu
    version.improved_story = improved_story
    version.generated_acceptance_criteria = acceptance_criteria
    
    await db.flush()
    await db.refresh(version)
    
    return version


async def can_edit_version(
    db: AsyncSession,
    version_id: str
) -> bool:
    """
    Vérifie si une version peut être modifiée.
    Une version approuvée (APPROVED) ne peut PAS être modifiée.
    """
    version = await get_version_by_id(db, version_id)
    if not version:
        return False
    
    return version.decision_status != StoryDecision.APPROVED

async def reset_customization(
    db: AsyncSession,
    version_id: str
) -> UserStoryVersion | None:
    """
    Réinitialise le statut 'customized' d'une version.
    Utile si l'utilisateur annule ses modifications.
    """
    version = await get_version_by_id(db, version_id)
    if not version:
        return None
    
    # Ne pas réinitialiser si la version est approuvée
    if version.decision_status == StoryDecision.APPROVED:
        raise PermissionError(f"Cannot reset approved version {version_id}")
    
    version.is_customized = False
    version.customized_at = None
    
    await db.flush()
    await db.refresh(version)
    
    return version