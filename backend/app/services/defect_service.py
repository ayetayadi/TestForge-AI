"""
Defect service — Tech Lead mode.

When the AI refinement pipeline detects a user story that is too low quality
to process (garbage_input), the system acts as a tech lead:
  1. Persists a Defect record in the local database.
  2. Optionally creates a Bug ticket in Jira (best-effort, never blocks the flow).
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.defect import Defect
from app.models.enums import DefectSeverity, DefectStatus
from app.models.user_story import UserStory

logger = logging.getLogger(__name__)

# Score below which we also flag as CRITICAL (even if not garbage)
CRITICAL_SCORE_THRESHOLD = 20.0
HIGH_SCORE_THRESHOLD = 35.0


def _severity_from_result(workflow_status: str, initial_score: float) -> DefectSeverity:
    if workflow_status == "garbage_input":
        return DefectSeverity.CRITICAL
    if initial_score < CRITICAL_SCORE_THRESHOLD:
        return DefectSeverity.HIGH
    if initial_score < HIGH_SCORE_THRESHOLD:
        return DefectSeverity.MEDIUM
    return DefectSeverity.LOW


def _build_jira_description(
    issue_key: str,
    title: str,
    initial_score: float,
    detected_issues: List[str],
    workflow_status: str,
) -> List[str]:
    paragraphs = [
        f"[TestForge AI — Tech Lead Report]",
        f"User Story: {issue_key} — {title}",
        f"Initial Quality Score: {initial_score:.1f}/100  |  Pipeline status: {workflow_status}",
        "Detected Issues:",
    ]
    for issue in detected_issues:
        paragraphs.append(f"  • {issue}")
    paragraphs.append(
        "This defect was automatically detected by the TestForge AI refinement pipeline "
        "and requires attention from the story author or product owner."
    )
    return paragraphs


async def create_defect(
    db: AsyncSession,
    user_story: UserStory,
    version_id: Optional[str],
    detected_issues: List[str],
    initial_score: float,
    workflow_status: str,
    jira_client=None,
) -> Defect:
    """
    Create a Defect record in DB and optionally a Bug ticket in Jira.
    Jira creation is best-effort: failures are logged but never propagate.
    """
    severity = _severity_from_result(workflow_status, initial_score)
    project_key = user_story.issue_key.rsplit("-", 1)[0] if "-" in user_story.issue_key else None

    title = (
        f"[DEFECT] {user_story.issue_key} — User story quality too low to process"
    )
    description = (
        f"Story '{user_story.issue_key}' scored {initial_score:.1f}/100 "
        f"(status: {workflow_status}). "
        f"Issues: {', '.join(detected_issues) if detected_issues else 'No details available.'}"
    )

    defect = Defect(
        id=str(uuid.uuid4()),
        user_story_id=user_story.id,
        user_story_version_id=version_id,
        title=title,
        description=description,
        severity=severity,
        status=DefectStatus.OPEN,
        detected_issues=detected_issues,
        initial_score=initial_score,
        jira_project_key=project_key,
    )

    db.add(defect)
    await db.flush()

    # ── Jira ticket creation (best-effort) ──────────────────────────
    if jira_client and project_key:
        try:
            paragraphs = _build_jira_description(
                issue_key=user_story.issue_key,
                title=user_story.title,
                initial_score=initial_score,
                detected_issues=detected_issues,
                workflow_status=workflow_status,
            )
            jira_priority = "Highest" if severity == DefectSeverity.CRITICAL else "High"
            result = await jira_client.create_issue(
                project_key=project_key,
                summary=title,
                description_paragraphs=paragraphs,
                issue_type="Bug",
                priority=jira_priority,
                labels=["testforge-ai", "auto-detected", "quality-defect"],
            )
            defect.jira_issue_key = result.get("key")
            logger.info(
                f"[DEFECT] Jira ticket created: {defect.jira_issue_key} "
                f"for story {user_story.issue_key}"
            )
        except Exception as exc:
            logger.warning(
                f"[DEFECT] Jira ticket creation failed for {user_story.issue_key}: {exc}"
            )

    logger.info(
        f"[DEFECT] Saved defect {defect.id} for story {user_story.issue_key} "
        f"(severity={severity.value}, jira={defect.jira_issue_key})"
    )
    return defect


async def get_defects_by_story(db: AsyncSession, user_story_id: str) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(Defect)
        .where(Defect.user_story_id == user_story_id)
        .order_by(Defect.created_at.desc())
    )
    defects = result.scalars().all()
    return [_serialize(d) for d in defects]


async def get_all_defects(db: AsyncSession) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(Defect).order_by(Defect.created_at.desc())
    )
    defects = result.scalars().all()
    return [_serialize(d) for d in defects]


async def update_defect_status(
    db: AsyncSession, defect_id: str, status: DefectStatus
) -> Optional[Dict[str, Any]]:
    result = await db.execute(select(Defect).where(Defect.id == defect_id))
    defect = result.scalar_one_or_none()
    if not defect:
        return None
    defect.status = status
    await db.commit()
    await db.refresh(defect)
    return _serialize(defect)


def _serialize(defect: Defect) -> Dict[str, Any]:
    return {
        "id": defect.id,
        "user_story_id": defect.user_story_id,
        "user_story_version_id": defect.user_story_version_id,
        "title": defect.title,
        "description": defect.description,
        "severity": defect.severity.value,
        "status": defect.status.value,
        "detected_issues": defect.detected_issues or [],
        "initial_score": defect.initial_score,
        "jira_issue_key": defect.jira_issue_key,
        "jira_project_key": defect.jira_project_key,
        "created_at": defect.created_at.isoformat() if defect.created_at else None,
        "updated_at": defect.updated_at.isoformat() if defect.updated_at else None,
    }
