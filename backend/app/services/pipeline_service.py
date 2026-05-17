import asyncio
import logging
from typing import List, Dict, Optional, Any, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_story import UserStory
from app.repositories.user_story_repository import (
    get_user_stories_by_project_id,
    count_user_stories_by_project,
    get_user_story_by_id,
)
from app.repositories.project_repository import get_project_by_id
from app.services.user_story_version_service import start_version
from app.workers.us_worker import submit_version

logger = logging.getLogger(__name__)


async def _notify_skipped_story(db: AsyncSession, us: UserStory, reason: str) -> None:
    """Notifie le PO sur Jira et envoie un SSE in-app quand une US est skippée."""
    print(f"[NOTIFY_SKIPPED] ▶ {us.issue_key} | raison: {reason}")
    try:
        from app.models.jira_project import JiraProject
        from app.models.jira_connection import JiraConnection
        from app.services.jira_session_manager import JiraSessionManager
        from app.services.notification_service import NotificationService

        proj_row = await db.execute(
            select(JiraProject).where(JiraProject.id == us.project_id)
        )
        jira_project = proj_row.scalar_one_or_none()
        project_key = jira_project.project_key if jira_project else None
        if not project_key:
            return

        jira_client = None
        try:
            row = await db.execute(
                select(JiraConnection)
                .join(JiraProject, JiraProject.jira_connection_id == JiraConnection.id)
                .where(JiraProject.id == us.project_id)
            )
            conn = row.scalar_one_or_none()
            if conn and conn.is_active:
                manager = JiraSessionManager(db)
                jira_client = await manager.get_client(conn)
        except Exception as exc:
            print(f"[NOTIFY_SKIPPED] ⚠️ Client Jira indisponible: {exc}")

        # SSE in-app + commentaire Jira (via NotificationService)
        notif_service = NotificationService(db, jira_client)
        await notif_service.notify_ambiguous_story(
            issue_key=us.issue_key,
            project_key=project_key,
            ambiguity_reasons=[reason],
        )
        print(f"[NOTIFY_SKIPPED] ✅ Notification envoyée pour {us.issue_key}")

    except Exception as exc:
        print(f"[NOTIFY_SKIPPED] ❌ {us.issue_key}: {type(exc).__name__}: {exc}")
        logger.warning(f"[NOTIFY_SKIPPED] Failed to notify {us.issue_key}: {exc}")


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
    skipped_stories: List[Tuple[UserStory, str]] = []
    states = []

    try:
        for us in user_stories:
            try:
                version_id, state = await start_version(db, us, reset=False)
            except ValueError as e:
                reason = str(e)
                skipped.append({"issue_key": us.issue_key, "reason": reason})
                skipped_stories.append((us, reason))
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

    # Notify PO on Jira for each story that was skipped (best-effort)
    if skipped_stories:
        await asyncio.gather(*[
            _notify_skipped_story(db, us, reason)
            for us, reason in skipped_stories
        ], return_exceptions=True)

    return {
        "total_requests": len(user_stories),
        "total_versions": len(versions),
        "skipped": skipped,
        "versions": versions,
    }