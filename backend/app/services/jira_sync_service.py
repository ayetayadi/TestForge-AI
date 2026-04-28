"""
Jira sync service — detects changes in Jira and synchronises TestForge AI.

The JiraChangeDetector (diff logic) now lives in notification_service.py to
avoid duplication. This module focuses on orchestration:
  1. Fetch fresh stories from Jira.
  2. Compute diff via notification_service.JiraChangeDetector.
  3. Import added/updated stories into the DB.
  4. Notify all relevant parties via NotificationService.
"""

import logging
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.jira_session_manager import JiraSessionManager
from app.services.notification_service import NotificationService, JiraChangeDetector

logger = logging.getLogger(__name__)


class JiraSyncOrchestrator:
    """Orchestrates detection, import and notification for a Jira project sync."""

    def __init__(self, db: AsyncSession, current_user):
        self.db = db
        self.current_user = current_user

    async def sync(self, project_key: str) -> Dict[str, Any]:
        """
        Full sync cycle for a project.

        Returns the change dict: {"added": [...], "updated": [...], "deleted": [...]}
        """
        logger.info("Sync started — project=%s user=%s", project_key, self.current_user.email)

        jira_stories = await self._fetch_jira_stories(project_key)

        detector = JiraChangeDetector(self.db)
        changes = await detector.detect(project_key, jira_stories)

        logger.info(
            "Sync diff — project=%s added=%d updated=%d deleted=%d",
            project_key,
            len(changes["added"]),
            len(changes["updated"]),
            len(changes["deleted"]),
        )

        if changes["added"] or changes["updated"]:
            await self._import_stories(project_key)

        if changes["deleted"]:
            await self._remove_deleted(changes["deleted"])

        # Notify in-app + Jira if there are any changes
        if any(changes.values()):
            notif_service = NotificationService(
                self.db,
                jira_client=await self._get_jira_client(),
            )
            await notif_service.notify_jira_changes(project_key, changes)

        logger.info("Sync finished — project=%s", project_key)
        return changes

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_jira_client(self):
        try:
            manager = JiraSessionManager(self.db)
            conn = await manager.get_connection(self.current_user.id)
            return await manager.get_client(conn)
        except Exception as exc:
            logger.warning("Could not get Jira client for notifications: %s", exc)
            return None

    async def _fetch_jira_stories(self, project_key: str) -> List[Dict]:
        try:
            client = await self._get_jira_client()
            if client is None:
                return []
            return await client.get_stories(project_key)
        except Exception as exc:
            logger.error("Failed to fetch stories from Jira: %s", exc)
            return []

    async def _import_stories(self, project_key: str) -> None:
        try:
            from app.services.project_service import import_project_by_key
            await import_project_by_key(
                self.db,
                project_key,
                self.current_user,
                notify_changes=False,
            )
        except Exception as exc:
            logger.error("Failed to import stories: %s", exc)

    async def _remove_deleted(self, deleted_stories) -> None:
        """Mark deleted Jira stories as removed in the DB."""
        try:
            from sqlalchemy import delete
            from app.models.user_story import UserStory
            keys = [s.issue_key for s in deleted_stories]
            if keys:
                await self.db.execute(
                    delete(UserStory).where(UserStory.issue_key.in_(keys))
                )
                await self.db.commit()
                logger.info("Removed %d deleted stories from DB", len(keys))
        except Exception as exc:
            logger.error("Failed to remove deleted stories: %s", exc)


# Keep backward-compat alias used by sync_jira.py
JiraChangeDetector = JiraChangeDetector  # re-exported from notification_service

async def manual_sync_endpoint(db: AsyncSession, project_key: str, current_user):
    orchestrator = JiraSyncOrchestrator(db, current_user)
    return await orchestrator.sync(project_key)
