from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.jira_sync_service import JiraSyncOrchestrator
from app.services.notification_service import JiraChangeDetector

router = APIRouter(prefix="/sync", tags=["Synchronisation"])


@router.post("/jira/{project_key}")
async def sync_jira_changes(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Sync Jira changes into TestForge AI.
    Detects added / updated / deleted stories and notifies all parties.
    """
    try:
        orchestrator = JiraSyncOrchestrator(db, current_user)
        changes = await orchestrator.sync(project_key)

        return {
            "success": True,
            "message": f"Synchronisation terminée pour {project_key}",
            "changes": {
                "added": len(changes["added"]),
                "updated": len(changes["updated"]),
                "deleted": len(changes["deleted"]),
                "added_keys": [s["key"] for s in changes["added"]],
                "updated_keys": [s["key"] for s in changes["updated"]],
                "deleted_keys": [
                    s.issue_key if hasattr(s, "issue_key") else s.get("key", "?")
                    for s in changes["deleted"]
                ],
            },
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/jira/{project_key}/check")
async def check_jira_changes(
    project_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Dry-run: check what has changed in Jira without importing anything.
    """
    try:
        from app.services.jira_session_manager import JiraSessionManager

        manager = JiraSessionManager(db)
        conn = await manager.get_connection(current_user.id)
        client = await manager.get_client(conn)

        jira_stories = await client.get_stories(project_key)

        detector = JiraChangeDetector(db)
        changes = await detector.detect(project_key, jira_stories)

        return {
            "has_changes": bool(changes["added"] or changes["updated"] or changes["deleted"]),
            "added": len(changes["added"]),
            "updated": len(changes["updated"]),
            "deleted": len(changes["deleted"]),
            "details": {
                "added_keys": [s["key"] for s in changes["added"]],
                "updated_keys": [s["key"] for s in changes["updated"]],
                "deleted_keys": [s.issue_key for s in changes["deleted"]],
            },
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))
