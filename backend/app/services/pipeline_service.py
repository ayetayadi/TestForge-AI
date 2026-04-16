from typing import List, Dict, Optional, Any
from sqlalchemy import select
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_story import UserStory
from app.repositories.user_story_repository import (
    get_user_stories_by_project_id,
    count_user_stories_by_project,
    get_user_story_by_id,
)
from app.repositories.project_repository import get_project_by_id
from app.services.user_story_version_service import start_version
from app.workers.asyncio_workers import submit_version


def validate_input(issue_keys: Optional[List[str]], project_id: Optional[str]) -> None:
    """Valide les paramètres d'entrée"""
    if not issue_keys and not project_id:
        raise ValueError("Provide issue_keys or project_id")

    if issue_keys and project_id:
        raise ValueError("Use either issue_keys OR project_id")


async def validate_project_exists(db: AsyncSession, project_id: str) -> None:
    """Vérifie que le projet existe"""
    project = await get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")


async def validate_project_has_stories(db: AsyncSession, project_id: str) -> None:
    """Vérifie que le projet a des stories"""
    count = await count_user_stories_by_project(db, project_id)
    if count == 0:
        raise ValueError("Project has no user stories")


async def run_pipeline(
    db: AsyncSession,
    issue_keys: Optional[List[str]],
    project_id: Optional[str],
) -> Dict[str, Any]:
    """
    Exécute le pipeline pour une liste de stories.
    
    Args:
        db: Session database
        issue_keys: Liste des clés Jira (ex: ["PROJ-1", "PROJ-2"])
        project_id: ID du projet
        
    Returns:
        Dictionnaire avec les résultats
    """

    # ============================================================
    # VALIDATION
    # ============================================================
    validate_input(issue_keys, project_id)

    # Normaliser (enlever les doublons)
    if issue_keys:
        issue_keys = list(dict.fromkeys(issue_keys))

    # ============================================================
    # CHARGER LES STORIES
    # ============================================================
    if issue_keys:
        result = await db.execute(
            select(UserStory).where(UserStory.issue_key.in_(issue_keys))
        )
        user_stories = result.scalars().all()

        if len(user_stories) != len(issue_keys):
            found_keys = {s.issue_key for s in user_stories}
            missing = [k for k in issue_keys if k not in found_keys]
            raise ValueError(f"Some stories not found: {missing}")

    else:
        await validate_project_exists(db, project_id)
        await validate_project_has_stories(db, project_id)

        user_stories = await get_user_stories_by_project_id(db, project_id)

    if not user_stories:
        raise ValueError("No stories found")

    if len(user_stories) > 100:
        raise ValueError("Too many user stories (max 100)")

    # ============================================================
    # LANCER LES VERSIONS
    # ============================================================
    versions = []
    skipped = []
    states = []

    try:
        for us in user_stories:
            try:
                version_id, state = await start_version(db, us, reset=False)
            except ValueError as e:
                skipped.append({
                    "issue_key": us.issue_key,
                    "reason": str(e)
                })
                continue

            states.append(state)

            versions.append({
                "version_id": version_id,
                "issue_key": us.issue_key,
            })

        await db.commit()

    except Exception:
        await db.rollback()
        raise

    # ============================================================
    # EXÉCUTION ASYNCHRONE (hors transaction)
    # ============================================================
    await asyncio.gather(*[
        submit_version(state) for state in states
    ], return_exceptions=True)

    return {
        "total_requests": len(user_stories),
        "total_versions": len(versions),
        "skipped": skipped,
        "versions": versions,
    }