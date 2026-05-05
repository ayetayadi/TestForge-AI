"""
Notification service for TestForge AI.

Responsibilities:
  1. Persist notifications to DB (so users who reconnect see missed notifications).
  2. Push real-time events via SSE (existing sse_manager).
  3. Post Atlassian Document Format comments to Jira when relevant.

SSE channel convention:
  - "notifications:{project_key}"  → project-scoped events (Jira sync, quality issues)
  - Any component subscribes with GET /notifications/stream/{project_key}
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.notification import Notification
from app.models.user_story import UserStory
from app.streaming.sse_manager import push_event

logger = logging.getLogger(__name__)


def _sse_channel(project_key: str) -> str:
    return f"notifications:{project_key}"


class NotificationService:
    """Centralised multi-team notification service."""

    def __init__(self, db: AsyncSession, jira_client=None):
        self.db = db
        self.jira_client = jira_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def notify_jira_changes(
        self,
        project_key: str,
        changes: Dict[str, List],
    ) -> None:
        """
        Called after a Jira sync. Persists one notification per change type
        and pushes a single SSE batch event so the frontend can refresh.
        """
        added = changes.get("added", [])
        updated = changes.get("updated", [])
        deleted = changes.get("deleted", [])

        print(f"\n[NOTIFY_JIRA] ▶ notify_jira_changes appelé pour {project_key}")
        print(f"[NOTIFY_JIRA]   ajoutées  : {[s['key'] for s in added]}")
        print(f"[NOTIFY_JIRA]   modifiées : {[s['key'] for s in updated]}")
        print(f"[NOTIFY_JIRA]   supprimées: {[s.issue_key if hasattr(s, 'issue_key') else s.get('key','?') for s in deleted]}")

        if not any([added, updated, deleted]):
            print(f"[NOTIFY_JIRA] ⏭️ Aucun changement — notification annulée")
            return

        parts = []
        if added:
            parts.append(f"{len(added)} US ajoutée(s)")
        if updated:
            parts.append(f"{len(updated)} US modifiée(s)")
        if deleted:
            parts.append(f"{len(deleted)} US supprimée(s)")

        title = f"Synchronisation Jira — {', '.join(parts)}"
        body_lines = ["Le Product Owner a modifié des User Stories dans Jira."]

        if added:
            body_lines.append(f"\nAjoutées : {', '.join(s['key'] for s in added)}")
        if updated:
            body_lines.append(f"Modifiées : {', '.join(s['key'] for s in updated)}")
        if deleted:
            deleted_keys = [
                s.issue_key if hasattr(s, "issue_key") else s.get("key", "?")
                for s in deleted
            ]
            body_lines.append(f"Supprimées : {', '.join(deleted_keys)}")

        print(f"[NOTIFY_JIRA] 💾 Persistence en base...")
        notif = await self._persist(
            project_key=project_key,
            issue_key=None,
            notif_type="story_updated" if updated else "story_added" if added else "story_deleted",
            title=title,
            body="\n".join(body_lines),
            severity="info",
        )
        print(f"[NOTIFY_JIRA] ✅ Notification persistée (id={notif.id})")

        channel = _sse_channel(project_key)
        print(f"[NOTIFY_JIRA] 📡 Push SSE sur channel '{channel}'...")
        await push_event(
            channel,
            "jira_sync",
            {
                "id": notif.id,
                "title": notif.title,
                "body": notif.body,
                "severity": notif.severity,
                "added": [s["key"] for s in added],
                "updated": [s["key"] for s in updated],
                "deleted": [
                    s.issue_key if hasattr(s, "issue_key") else s.get("key", "?")
                    for s in deleted
                ],
                "timestamp": notif.created_at.isoformat(),
            },
        )
        print(f"[NOTIFY_JIRA] ✅ SSE envoyé")

    async def notify_quality_issue(
        self,
        issue_key: str,
        project_key: str,
        initial_score: float,
        detected_issues: List[str],
        improved_story: Optional[str] = None,
    ) -> None:
        """
        Called when the refinement pipeline detects an ambiguous / low-quality US.
        Persists a notification AND posts a comment to Jira so the PO is aware.
        """
        score_pct = round(initial_score * 100, 1)
        title = f"Alerte qualité — {issue_key} (score {score_pct}/100)"

        body_parts = [
            f"La user story {issue_key} a été analysée et présente une qualité insuffisante.",
            f"Score qualité : {score_pct}/100",
            "",
            "Problèmes détectés :",
        ] + [f"  • {p}" for p in detected_issues[:8]]

        if improved_story:
            preview = improved_story[:400] + "..." if len(improved_story) > 400 else improved_story
            body_parts += ["", "Version améliorée proposée :", preview]

        notif = await self._persist(
            project_key=project_key,
            issue_key=issue_key,
            notif_type="quality_issue",
            title=title,
            body="\n".join(body_parts),
            severity="warning",
        )

        await push_event(
            _sse_channel(project_key),
            "quality_issue",
            {
                "id": notif.id,
                "issue_key": issue_key,
                "title": notif.title,
                "score": score_pct,
                "issues": detected_issues,
                "severity": notif.severity,
                "timestamp": notif.created_at.isoformat(),
            },
        )

        # Post to Jira so the PO sees it in their board
        jira_posted = await self._post_jira_quality_comment(
            issue_key, score_pct, detected_issues, improved_story
        )
        if jira_posted:
            notif.jira_comment_posted = True
            await self.db.commit()

    async def notify_story_approved(
        self,
        issue_key: str,
        project_key: str,
        refined_content: str,
    ) -> None:
        """
        Called when the tester approves a refined user story.
        Notifies Jira (PO) via comment that an improved version is available.
        """
        title = f"User Story approuvée — {issue_key}"
        body = (
            f"Le testeur a approuvé la version raffinée de {issue_key}.\n\n"
            f"Version approuvée :\n{refined_content[:500]}"
        )

        notif = await self._persist(
            project_key=project_key,
            issue_key=issue_key,
            notif_type="story_approved",
            title=title,
            body=body,
            severity="info",
        )

        await push_event(
            _sse_channel(project_key),
            "story_approved",
            {
                "id": notif.id,
                "issue_key": issue_key,
                "title": notif.title,
                "timestamp": notif.created_at.isoformat(),
            },
        )

        paragraphs = [
            "TestForge AI — User Story approuvée",
            "",
            f"Le testeur a validé une version améliorée de cette user story.",
            "La version raffinée est maintenant active dans TestForge AI.",
            "",
            "Version approuvée :",
            refined_content[:600],
        ]
        jira_posted = await self._post_jira_comment(issue_key, paragraphs)
        if jira_posted:
            notif.jira_comment_posted = True
            await self.db.commit()

    async def notify_ambiguous_story(
        self,
        issue_key: str,
        project_key: str,
        ambiguity_reasons: List[str],
    ) -> None:
        """
        Called when the pipeline detects an ambiguous US that the PO must fix.
        Posts a Jira comment tagging the PO and persists an in-app notification.
        """
        title = f"User Story ambiguë — action requise du PO — {issue_key}"
        body = (
            f"La user story {issue_key} contient des ambiguïtés qui bloquent la génération des tests.\n\n"
            + "\n".join(f"  • {r}" for r in ambiguity_reasons)
        )

        notif = await self._persist(
            project_key=project_key,
            issue_key=issue_key,
            notif_type="ambiguous_story",
            title=title,
            body=body,
            severity="error",
        )

        await push_event(
            _sse_channel(project_key),
            "ambiguous_story",
            {
                "id": notif.id,
                "issue_key": issue_key,
                "title": notif.title,
                "reasons": ambiguity_reasons,
                "severity": notif.severity,
                "timestamp": notif.created_at.isoformat(),
            },
        )

        paragraphs = [
            "TestForge AI — Action requise",
            "",
            f"La user story {issue_key} contient des ambiguïtés qui empêchent la génération automatique des tests.",
            "",
            "Problèmes détectés :",
        ] + [f"  • {r}" for r in ambiguity_reasons] + [
            "",
            "Merci de corriger cette user story afin de débloquer le processus de test.",
        ]
        jira_posted = await self._post_jira_comment(issue_key, paragraphs)
        if jira_posted:
            notif.jira_comment_posted = True
            await self.db.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _persist(
        self,
        *,
        project_key: Optional[str],
        issue_key: Optional[str],
        notif_type: str,
        title: str,
        body: str,
        severity: str,
    ) -> Notification:
        notif = Notification(
            project_key=project_key,
            issue_key=issue_key,
            type=notif_type,
            title=title,
            body=body,
            severity=severity,
        )
        self.db.add(notif)
        await self.db.commit()
        await self.db.refresh(notif)
        logger.info("Notification persisted: type=%s project=%s issue=%s", notif_type, project_key, issue_key)
        return notif

    async def _post_jira_comment(self, issue_key: str, paragraphs: List[str]) -> bool:
        if not self.jira_client:
            return False
        try:
            await self.jira_client.add_comment(issue_key, paragraphs)
            logger.info("Jira comment posted on %s", issue_key)
            return True
        except Exception as exc:
            logger.warning("Failed to post Jira comment on %s: %s", issue_key, exc)
            return False

    async def _post_jira_quality_comment(
        self,
        issue_key: str,
        score_pct: float,
        detected_issues: List[str],
        improved_story: Optional[str],
    ) -> bool:
        paragraphs = [
            "TestForge AI — Alerte qualité",
            "",
            f"La user story {issue_key} a été analysée par TestForge AI.",
            f"Score qualité : {score_pct}/100",
            "",
            "Problèmes détectés :",
        ] + [f"  • {p}" for p in detected_issues[:8]]

        if improved_story:
            preview = improved_story[:500] + "..." if len(improved_story) > 500 else improved_story
            paragraphs += [
                "",
                "Version améliorée proposée par l'IA :",
                preview,
                "",
                "Vous pouvez copier cette version dans Jira ou l'améliorer manuellement.",
            ]
        else:
            paragraphs += [
                "",
                "Suggestions : ajoutez des critères d'acceptation clairs et précisez la valeur métier.",
            ]

        return await self._post_jira_comment(issue_key, paragraphs)


# ---------------------------------------------------------------------------
# Change detector (single implementation — replaces the duplicate in
# jira_sync_service.py and the old StoryChangeDetector in this file)
# ---------------------------------------------------------------------------

class JiraChangeDetector:
    """Compares Jira stories against DB state and returns a diff."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def detect(
        self,
        project_key: str,
        jira_stories: List[Dict[str, Any]],
    ) -> Dict[str, List]:
        print(f"\n[DETECTOR] ▶ detect() appelé pour {project_key}")
        print(f"[DETECTOR]   {len(jira_stories)} stories reçues de Jira")

        from app.models.jira_project import JiraProject
        proj_result = await self.db.execute(
            select(JiraProject).where(JiraProject.project_key == project_key)
        )
        jira_project = proj_result.scalar_one_or_none()

        if jira_project is None:
            print(f"[DETECTOR] ❌ Projet {project_key} introuvable en base — diff impossible")
            return {"added": [], "updated": [], "deleted": []}

        print(f"[DETECTOR] ✅ Projet trouvé en base (id={jira_project.id})")

        stories_result = await self.db.execute(
            select(UserStory).where(UserStory.project_id == jira_project.id)
        )
        db_stories: Dict[str, UserStory] = {
            s.issue_key: s for s in stories_result.scalars().all()
        }

        jira_keys = {s["key"] for s in jira_stories}
        db_keys = set(db_stories.keys())

        print(f"[DETECTOR]   Stories en DB  : {len(db_keys)} → {sorted(db_keys)}")
        print(f"[DETECTOR]   Stories Jira   : {len(jira_keys)} → {sorted(jira_keys)}")

        added = [s for s in jira_stories if s["key"] not in db_keys]
        deleted = [db_stories[k] for k in db_keys - jira_keys]
        updated = []
        for s in jira_stories:
            if s["key"] in db_keys:
                changed = self._has_changed(db_stories[s["key"]], s)
                print(f"[DETECTOR]   _has_changed({s['key']}) → {changed}")
                if changed:
                    updated.append(s)

        print(f"[DETECTOR] 📊 Résultat diff:")
        print(f"[DETECTOR]   ✨ Ajoutées  : {[s['key'] for s in added]}")
        print(f"[DETECTOR]   📝 Modifiées : {[s['key'] for s in updated]}")
        print(f"[DETECTOR]   🗑️ Supprimées: {[s.issue_key for s in deleted]}")

        return {"added": added, "updated": updated, "deleted": deleted}

    @staticmethod
    def _has_changed(db_story: UserStory, jira_story: Dict[str, Any]) -> bool:
        # Apply the same pipeline as import so we compare apples to apples
        from app.utils.mapper_utils import map_jira_issue
        mapped = map_jira_issue(jira_story)

        new_desc = (mapped.get("description") or "").strip()
        old_desc = (db_story.description or "").strip()
        new_ac = sorted(mapped.get("acceptance_criteria") or [])
        old_ac = sorted(db_story.acceptance_criteria or [])

        desc_changed = new_desc != old_desc
        ac_changed = new_ac != old_ac
        if desc_changed:
            print(f"[HAS_CHANGED]   {db_story.issue_key} desc changée")
            print(f"[HAS_CHANGED]     DB  : {repr(old_desc[:80])}")
            print(f"[HAS_CHANGED]     Jira: {repr(new_desc[:80])}")
        if ac_changed:
            print(f"[HAS_CHANGED]   {db_story.issue_key} AC changés")
            print(f"[HAS_CHANGED]     DB  : {old_ac}")
            print(f"[HAS_CHANGED]     Jira: {new_ac}")
        return desc_changed or ac_changed
