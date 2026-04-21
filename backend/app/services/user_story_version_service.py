from datetime import datetime
from typing import Any, Dict, Optional, Tuple, List
import uuid
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user_story import UserStory
from app.models.user_story_version import UserStoryVersion
from app.models.enums import AgentStatus, StoryDecision
from app.repositories.user_story_repository import get_user_story_by_id
from app.repositories.user_story_version_repository import (
    create_version,
    get_latest_version,
    get_selected_version,
    get_version_by_id,
    get_versions_by_story_id,
    reset_customization,
    update_version_content,
)
from app.ai_workflows.user_story_refinement.utils.text_processing import detect_language
from app.workers.asyncio_workers import submit_version


logger = logging.getLogger(__name__)

async def get_final_details(db: AsyncSession, user_story_id: str):
    """Récupère les détails finaux d'une story"""
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


async def start_version(
    db: AsyncSession,
    user_story,
    reset: bool = False
) -> Tuple[str, Dict[str, Any]]:
    """
    Start a new version for a user story.
    NE PAS créer de version en DB ici - juste préparer le state.
    """
    
    latest = await get_latest_version(db, user_story.id)
    
    print(f"[START_VERSION] {user_story.issue_key}")
    print(f"[START_VERSION] latest_version exists: {latest is not None}")

    # ============================================================
    # Determine input story + AC
    # ============================================================
    if reset:
        raw_story = user_story.description
        acceptance_criteria = user_story.acceptance_criteria or []
    else:
        raw_story = (
            latest.improved_story
            if latest else user_story.description
        )
        acceptance_criteria = (
            latest.generated_acceptance_criteria
            if latest else user_story.acceptance_criteria or []
        )

    # ============================================================
    # Générer ID mais NE PAS créer en DB
    # ============================================================
    version_id = str(uuid.uuid4())
    
    try:
        language = detect_language(raw_story)
    except Exception:
        language = "en"

    # ============================================================
    # Create state for orchestrator (PAS de version en DB)
    # ============================================================
    state = {
        "version_id": version_id,
        "jira_id": user_story.issue_key,
        "raw_story": raw_story,
        "user_story_id": user_story.id,
        "acceptance_criteria": acceptance_criteria,
        "language": language,
        "retry_count": 0  # ← AJOUTÉ
    }
    
    print(f"[START_VERSION] {user_story.issue_key}")
    print(f"  - Version ID: {version_id} (to be created after AI processing)")
    print(f"  - Story: {raw_story[:50]}...")
    print(f"  - AC count: {len(acceptance_criteria)}")
    print(f"  - Detected language: {language}")
    
    return version_id, state


async def apply_decision(
    db: AsyncSession,
    user_story_id: str,
    decision: str,
    version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Apply user decision to a version.
    
    Decisions:
    - approve: Mark version as approved
    - relaunch: Start new version
    - reject_keep: Reject but keep original
    """
    
    try:
        # ============================================================
        # Get user story
        # ============================================================
        user_story = await get_user_story_by_id(db, user_story_id)

        if not user_story:
            raise HTTPException(404, "User story not found")

        # ============================================================
        # Validate decision + version_id
        # ============================================================
        if decision in ("approve", "relaunch"):
            if not version_id:
                raise HTTPException(400, "version_id is required for this decision")

        # ============================================================
        # Get version
        # ============================================================
        version = await get_version_by_id(db, version_id) if version_id else None

        if version_id and not version:
            raise HTTPException(404, "Version not found")

        if version and version.user_story_id != user_story_id:
            raise HTTPException(400, "Version does not belong to this story")

        # ============================================================
        # APPROVE
        # ============================================================
        if decision == "approve":
            
            # Mark all other versions as rejected
            versions = await get_versions_by_story_id(db, user_story_id)

            for v in versions:
                if v.id != version.id:
                    v.decision_status = StoryDecision.REJECTED

            # Mark this version as approved
            version.decision_status = StoryDecision.APPROVED
            
            # Update story current score
            user_story.current_score = version.final_score

            await db.commit()

            return {
                "message": "Version approved",
                "version_id": version.id,
                "final_score": version.final_score
            }

        # ============================================================
        # RELAUNCH
        # ============================================================
        elif decision == "relaunch":
            
            # Mark version as rejected
            #if version:
            #    version.decision_status = StoryDecision.REJECTED
            #    await db.flush()

            # Start new version with original story
            new_version_id, state = await start_version(
                db,
                user_story,
                reset=True
            )

            await db.commit()

            # Submit version to queue
            try:
                await submit_version(state)
            except Exception as e:
                print(f"[SUBMIT ERROR] {e}")
                raise HTTPException(500, f"Failed to submit version: {e}")

            return {
                "message": "Version relaunched",
                "new_version_id": new_version_id,
                "previous_version_id": version_id
            }

        # ============================================================
        # REJECT KEEP
        # ============================================================
        elif decision == "reject_keep":
            
            # Mark version as rejected, keep original
            if version:
                version.decision_status = StoryDecision.REJECTED
                await db.commit()

            return {
                "message": "Version rejected, original kept",
                "version_id": version_id
            }

        else:
            raise HTTPException(400, "Invalid decision. Use: approve, relaunch, reject_keep")

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, str(e))


async def get_versions_by_issue_keys(
    db: AsyncSession,
    issue_keys: List[str]
) -> Dict[str, Any]:
    """
    Get versions for multiple issue keys.
    
    Returns latest version (approved or latest by date).
    
    Args:
        db: Database session
        issue_keys: List of Jira issue keys
        
    Returns:
        Dict mapping issue_key → version info
    """

    if not issue_keys:
        return {}

    # ============================================================
    # Query user stories and their versions
    # ============================================================
    result = await db.execute(
        select(UserStory)
        .where(UserStory.issue_key.in_(issue_keys))
    )
    stories = result.scalars().all()

    # ============================================================
    # Map issue_key → story
    # ============================================================
    story_map: Dict[str, UserStory] = {
        story.issue_key: story for story in stories
    }

    # ============================================================
    # Get all versions for these stories
    # ============================================================
    story_ids = [story.id for story in stories]
    all_versions = []
    
    if story_ids:
        result = await db.execute(
            select(UserStoryVersion)
            .where(UserStoryVersion.user_story_id.in_(story_ids))
            .order_by(UserStoryVersion.started_at.desc())
        )
        all_versions = result.scalars().all()

    # ============================================================
    # Group versions by story_id
    # ============================================================
    versions_by_story: Dict[str, List[UserStoryVersion]] = {}
    for version in all_versions:
        versions_by_story.setdefault(version.user_story_id, []).append(version)

    response = {}

    # ============================================================
    # For each issue key, get best version
    # ============================================================
    for issue_key in issue_keys:
        story = story_map.get(issue_key)
        
        if not story:
            response[issue_key] = None
            continue

        story_versions = versions_by_story.get(story.id, [])

        if not story_versions:
            response[issue_key] = None
            continue

        # Get approved version
        approved_version = next(
            (v for v in story_versions if v.decision_status == StoryDecision.APPROVED),
            None
        )

        # Latest version (basé sur started_at)
        latest_version = max(
            story_versions,
            key=lambda v: v.started_at
        )

        display_version = approved_version or latest_version
        
        # Version en cours de traitement
        processing_version = next(
            (v for v in story_versions if v.agent_status == AgentStatus.PROCESSING),
            None
        )

        # ============================================================
        # Build response
        # ============================================================
        response[issue_key] = {
            "story_id": story.id,
            "issue_key": story.issue_key,
            "title": story.title,
            "current_score": story.current_score,
            "version_id": display_version.id,
            "agent_status": display_version.agent_status.value,
            "decision_status": display_version.decision_status.value,
            "improved_story": display_version.improved_story,
            "acceptance_criteria": display_version.generated_acceptance_criteria or [],
            "initial_score": display_version.initial_score or 0,
            "final_score": display_version.final_score or 0,
            "score_delta": (
                (display_version.final_score - display_version.initial_score)
                if display_version.initial_score is not None
                and display_version.final_score is not None
                else 0
            ),
            "testability_score": display_version.testability_score,
            "is_testable": display_version.is_testable,
            "testability_issues": display_version.testability_issues or [],
            "started_at": display_version.started_at.isoformat() if display_version.started_at else None,
            "completed_at": display_version.completed_at.isoformat() if display_version.completed_at else None,
            "has_processing": processing_version is not None,
            "processing_version_id": processing_version.id if processing_version else None,
            "versions_count": len(story_versions),
            "has_new_version": len(story_versions) > 1,
        }

    return response

async def edit_version(
    db: AsyncSession,
    version_id: str,
    improved_story: str,
    acceptance_criteria: List[str],
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Permet à l'utilisateur de modifier manuellement une version.
    """
    # 1. Validation du contenu
    _validate_content(improved_story, acceptance_criteria)  # Note: plus de self
    
    # 2. Récupérer la version
    version = await get_version_by_id(db, version_id)  # Note: db direct
    if not version:
        raise ValueError(f"Version {version_id} not found")
    
    # 3. Vérification : Version approuvée = NON modifiable
    if version.decision_status == StoryDecision.APPROVED:
        raise PermissionError(
            f"Cannot edit approved version {version_id}. "
            f"Approved versions are locked."
        )
    
    # 4. Vérifier si le contenu a vraiment changé
    if _is_content_identical(version, improved_story, acceptance_criteria):
        return {
            "status": "no_change",
            "message": "No changes detected",
            "version_id": version_id,
            "is_customized": version.is_customized,
            "customized_at": version.customized_at.isoformat() if version.customized_at else None
        }
    
    # 5. Mise à jour
    updated = await update_version_content(
        db,
        version_id,
        improved_story,
        acceptance_criteria
    )
    
    if not updated:
        raise ValueError(f"Failed to update version {version_id}")
    
    # 6. Commit
    await db.commit()
    
    logger.info(f"Version {version_id} manually edited by {user_id or 'anonymous'}")
    
    return {
        "status": "success",
        "message": "Version edited successfully",
        "version_id": version_id,
        "is_customized": updated.is_customized,
        "customized_at": updated.customized_at.isoformat() if updated.customized_at else None
    }


async def can_edit(
    db: AsyncSession,
    version_id: str
) -> Dict[str, Any]:
    """
    Vérifie si une version peut être modifiée.
    """
    version = await get_version_by_id(db, version_id)
    
    if not version:
        return {
            "can_edit": False,
            "reason": "Version not found",
            "is_approved": False,
            "is_customized": False
        }
    
    is_approved = version.decision_status == StoryDecision.APPROVED
    
    if is_approved:
        return {
            "can_edit": False,
            "reason": "Approved versions cannot be edited. They are locked.",
            "is_approved": True,
            "is_customized": version.is_customized
        }
    
    return {
        "can_edit": True,
        "reason": None,
        "is_approved": False,
        "is_customized": version.is_customized
    }


async def reset_to_original(
    db: AsyncSession,  # ← CORRIGÉ
    version_id: str,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Réinitialise une version personnalisée à son état original.
    """
    # 1. Récupérer la version
    version = await get_version_by_id(db, version_id)
    if not version:
        raise ValueError(f"Version {version_id} not found")
    
    # 2. Vérifier qu'elle est personnalisée
    if not version.is_customized:
        return {
            "status": "no_change",
            "message": "Version is not customized",
            "version_id": version_id,
            "is_customized": False
        }
    
    # 3. Vérifier qu'elle n'est pas approuvée
    if version.decision_status == StoryDecision.APPROVED:
        raise PermissionError(f"Cannot reset approved version {version_id}")
    
    # 4. Réinitialiser
    reset_version = await reset_customization(db, version_id)
    
    if not reset_version:
        raise ValueError(f"Failed to reset version {version_id}")
    
    await db.commit()
    
    logger.info(f"Version {version_id} reset by {user_id or 'anonymous'}")
    
    return {
        "status": "success",
        "message": "Version reset to original (customization flag removed)",
        "version_id": version_id,
        "is_customized": False,
        "customized_at": None
    }


# ⚠️ Ajouter ces fonctions helper (sans self)
def _validate_content(story: str, criteria: List[str]) -> None:
    """Valide le contenu d'une version"""
    if not story or len(story.strip()) < 10:
        raise ValueError("Story must be at least 10 characters long")
    
    if len(story) > 5000:
        raise ValueError("Story exceeds maximum length of 5000 characters")
    
    if not criteria or len(criteria) == 0:
        raise ValueError("At least one acceptance criterion is required")
    
    if len(criteria) > 50:
        raise ValueError("Maximum 50 acceptance criteria allowed")
    
    for i, criterion in enumerate(criteria):
        if not criterion or len(criterion.strip()) < 3:
            raise ValueError(f"Criterion {i+1} is too short (minimum 3 characters)")


def _is_content_identical(version, new_story: str, new_criteria: List[str]) -> bool:
    """Vérifie si le contenu est identique à l'original"""
    story_identical = version.improved_story == new_story
    
    criteria_identical = (
        len(version.generated_acceptance_criteria) == len(new_criteria) and
        all(a == b for a, b in zip(version.generated_acceptance_criteria, new_criteria))
    )
    
    return story_identical and criteria_identical