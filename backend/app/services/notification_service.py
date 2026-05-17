"""
Notification service for TestForge AI.

Responsibilities:
  1. Push real-time events via SSE (sse_manager).
  2. Post Atlassian Document Format comments to Jira when relevant.

SSE channel convention:
  - "notifications:{project_key}"  → project-scoped events (Jira sync, quality issues)
  - Any component subscribes with GET /notifications/stream/{project_key}
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user_story import UserStory
from app.streaming.sse_manager import push_event

logger = logging.getLogger(__name__)


def _sse_channel(project_key: str) -> str:
    return f"notifications:{project_key}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

        channel = _sse_channel(project_key)
        print(f"[NOTIFY_JIRA] 📡 Push SSE sur channel '{channel}'...")
        await push_event(
            channel,
            "jira_sync",
            {
                "title": title,
                "severity": "info",
                "added": [s["key"] for s in added],
                "updated": [s["key"] for s in updated],
                "deleted": [
                    s.issue_key if hasattr(s, "issue_key") else s.get("key", "?")
                    for s in deleted
                ],
                "timestamp": _now_iso(),
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
        score_pct = round(initial_score * 100, 1)
        title = f"Alerte qualité — {issue_key} (score {score_pct}/100)"

        await push_event(
            _sse_channel(project_key),
            "quality_issue",
            {
                "issue_key": issue_key,
                "title": title,
                "score": score_pct,
                "issues": detected_issues,
                "severity": "warning",
                "timestamp": _now_iso(),
            },
        )

        await self._post_jira_quality_comment(
            issue_key, score_pct, detected_issues, improved_story
        )

    async def notify_story_approved(
        self,
        issue_key: str,
        project_key: str,
        refined_content: str,
    ) -> None:
        title = f"User Story approuvée — {issue_key}"

        await push_event(
            _sse_channel(project_key),
            "story_approved",
            {
                "issue_key": issue_key,
                "title": title,
                "timestamp": _now_iso(),
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
        await self._post_jira_comment(issue_key, paragraphs)

    async def notify_ambiguous_story(
        self,
        issue_key: str,
        project_key: str,
        ambiguity_reasons: List[str],
    ) -> None:
        title = f"User Story ambiguë — action requise du PO — {issue_key}"

        await push_event(
            _sse_channel(project_key),
            "ambiguous_story",
            {
                "issue_key": issue_key,
                "title": title,
                "reasons": ambiguity_reasons,
                "severity": "error",
                "timestamp": _now_iso(),
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
        await self._post_jira_comment(issue_key, paragraphs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
# Change detector (diff Jira vs DB state)
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
