import asyncio
import os
import traceback
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlalchemy import select
from app.models.enums import WorkflowStatus, StoryDecision
from app.repositories.user_story_version_repository import get_best_version
from app.repositories.user_story_repository import get_user_story_by_id
from app.core.config import settings
from app.core.database import async_session_maker
from app.streaming.sse_manager import push_event
from app.ai_workflows.user_story_refinement.pipeline import get_pipeline
from app.models.user_story_version import UserStoryVersion
from app.services.defect_service import create_defect
from .us_queue import job_queue
from app.llm.llm_control import set_worker_api_key

logger = logging.getLogger(__name__)

MAX_WORKERS = settings.MAX_WORKERS
WORKFLOW_TIMEOUT = 120
MAX_RETRIES = 3

workers: List[asyncio.Task] = []


# ============================================================
# VALIDATION
# ============================================================

def _validate_state(state: Dict[str, Any]) -> None:
    required = ["version_id", "jira_id", "raw_story", "user_story_id"]
    for key in required:
        if key not in state:
            raise ValueError(f"Missing required field: {key}")
    if not state.get("raw_story") or not state["raw_story"].strip():
        raise ValueError("raw_story cannot be empty")


def normalize_ac(ac_list: List[str]) -> List[str]:
    return sorted([
        ac.strip().lower()
        for ac in (ac_list or [])
        if ac and ac.strip()
    ])


# ============================================================
# SAVE VERSION
# ============================================================

async def save_ai_version(
    db,
    version_id: str,
    user_story_id: str,
    result: Dict[str, Any],
    state: Dict[str, Any],
) -> UserStoryVersion:
    """Persist agent result as a new version — no commit (caller commits)."""

    from sqlalchemy import func
    
    # Obtenir le max version_number pour cette user story
    stmt = select(func.max(UserStoryVersion.version_number)).where(
        UserStoryVersion.user_story_id == user_story_id
    )
    max_version = await db.execute(stmt)
    max_num = max_version.scalar() or 0
    next_version_number = max_num + 1
    
    logger.info(f"Creating version {next_version_number} for story {user_story_id}")

    improved_story = result.get("improved_story", state["raw_story"])
    generated_ac = result.get("acceptance_criteria", state.get("acceptance_criteria", []))
    initial_score = float(result.get("initial_score", 0.0))
    final_score = float(result.get("final_score", 0.0))
    testability_score = float(result.get("testability_score", 0.0))
    is_testable = result.get("is_testable", False)
    testability_issues = result.get("testability_issues", [])
    iterations = result.get("iterations", 0)
    duration = result.get("duration_seconds", 0.0)
    workflow_status_str = result.get("workflow_status", "success")

    workflow_status = (
        WorkflowStatus.FAILED
        if workflow_status_str == "error"
        else WorkflowStatus.COMPLETED
    )

    version = UserStoryVersion(
        id=version_id,
        user_story_id=user_story_id,
        version_number=next_version_number,
        improved_story=improved_story,
        generated_acceptance_criteria=generated_ac,
        initial_score=initial_score,
        final_score=final_score,
        testability_score=testability_score,
        is_testable=is_testable,
        testability_issues=testability_issues,
        workflow_status=workflow_status,
        started_at=datetime.now(),
        completed_at=datetime.now(),
        decision_status=StoryDecision.PENDING,
    )

    db.add(version)
    await db.flush()

    story = await get_user_story_by_id(db, user_story_id)
    if story:
        story.current_score = final_score
        await db.flush()

    logger.info(f"Version created: {version.id} (v{next_version_number}), score={final_score:.3f}")
    return version


# ============================================================
# PROGRESS CALLBACK FACTORY
# ============================================================

def _make_progress_callback(version_id: str):
    async def cb(event_type: str, data: dict) -> None:
        await push_event(version_id, event_type, {**data, "timestamp": datetime.now().isoformat()})
    return cb


# Score below which we consider the story too ambiguous even if not garbage
AMBIGUOUS_SCORE_THRESHOLD = 0.40


async def _get_jira_client(db, user_story_id: str):
    """Return a JiraClient for the story's project, or None on any failure."""
    try:
        from app.models.user_story import UserStory
        from app.models.jira_project import JiraProject
        from app.models.jira_connection import JiraConnection
        from app.services.jira_session_manager import JiraSessionManager

        row = await db.execute(
            select(JiraConnection)
            .join(JiraProject, JiraProject.jira_connection_id == JiraConnection.id)
            .join(UserStory, UserStory.project_id == JiraProject.id)
            .where(UserStory.id == user_story_id)
        )
        conn = row.scalar_one_or_none()
        if not conn or not conn.is_active:
            return None

        manager = JiraSessionManager(db)
        return await manager.get_client(conn)
    except Exception as exc:
        logger.debug(f"[JIRA] Could not get client for story {user_story_id}: {exc}")
        return None


async def _notify_product_owner(
    db,
    user_story,
    jira_id: str,
    initial_score: float,
    workflow_status: str,
    detected_issues: List[str],
    version_id: str,
) -> Optional[str]:
    """
    Post a comment on the original Jira ticket asking the product owner
    to clarify the story. Returns the comment id or None on failure.
    """
    jira_client = await _get_jira_client(db, user_story.id)
    if not jira_client:
        logger.warning(f"[NOTIFY] No Jira client — skipping comment for {jira_id}")
        return None

    score_pct = round(initial_score * 100, 1)

    if workflow_status == "garbage_input":
        reason = "vide, trop courte ou incompréhensible"
    else:
        reason = "trop vague ou ambiguë pour être améliorée automatiquement"

    issues_lines = [f"  • {i}" for i in detected_issues] if detected_issues else ["  • Aucun détail disponible"]

    paragraphs = [
        "⚠️ TestForge AI — Alerte qualité User Story",
        f"La user story {jira_id} a été analysée automatiquement et ne peut pas être traitée car elle est {reason}.",
        f"Score qualité initial : {score_pct}/100  |  Statut pipeline : {workflow_status}",
        "Problèmes détectés :",
        *issues_lines,
        "Merci de préciser ou compléter cette user story (description, critères d'acceptation, valeur métier) avant de relancer l'analyse TestForge AI.",
    ]

    try:
        result = await jira_client.add_comment(jira_id, paragraphs)
        comment_id = result.get("id")
        logger.info(f"[NOTIFY] Comment posted on {jira_id} (comment_id={comment_id})")
        return comment_id
    except Exception as exc:
        logger.warning(f"[NOTIFY] Failed to post comment on {jira_id}: {exc}")
        return None


# ============================================================
# WORKER LOOP
# ============================================================

def _get_api_key_for_worker(worker_id: int) -> str:
    """Retourne la clé API dédiée à ce worker (1→KEY_1, 2→KEY_2, etc.)."""
    key_name = f"GROQ_API_KEY_{worker_id}"
    api_key = os.getenv(key_name, "")
    if not api_key:
        logger.warning(f"[US WORKER-{worker_id}] ⚠️ {key_name} not found, using fallback")
        api_key = os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY", ""))
    return api_key


async def async_worker(worker_id: int) -> None:
    api_key = _get_api_key_for_worker(worker_id)
    set_worker_api_key(api_key)

    key_preview = api_key[:15] + "..." if api_key else "NO_KEY"
    logger.info(f"[US WORKER-{worker_id}] 🚀 Started with dedicated key: {key_preview}")
    print(f"[WORKER-{worker_id}] started with key: {key_preview}")

    while True:
        state: Dict[str, Any] = await job_queue.get()

        if state is None:
            logger.info(f"Worker {worker_id} received stop signal")
            job_queue.task_done()
            break

        async with async_session_maker() as db:
            version_id = state.get("version_id")
            jira_id = state.get("jira_id", "?")
            retry_count = state.get("retry_count", 0)

            try:
                _validate_state(state)
                logger.info(f"Processing version: {version_id} (Jira: {jira_id}, retry: {retry_count})")

                await push_event(version_id, "processing", {
                    "message": "Starting agent...",
                    "jira_id": jira_id,
                    "version_id": version_id,
                    "timestamp": datetime.now().isoformat(),
                })

                try:
                    result = await asyncio.wait_for(
                        get_pipeline().run(
                            story=state["raw_story"],
                            acceptance_criteria=state.get("acceptance_criteria", []),
                            language=state.get("language", "en"),
                            jira_id=jira_id,
                            progress_callback=_make_progress_callback(version_id),
                        ),
                        timeout=WORKFLOW_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError(f"Agent timeout after {WORKFLOW_TIMEOUT}s")

                # errors are returned as a result dict, not raised
                if result.get("workflow_status") == "error":
                    logger.error(f"Agent reported error: {result.get('error')}")
                    failed_version = UserStoryVersion(
                        id=version_id,
                        user_story_id=state["user_story_id"],
                        improved_story=state["raw_story"],
                        generated_acceptance_criteria=state.get("acceptance_criteria", []),
                        workflow_status=WorkflowStatus.FAILED,
                        started_at=datetime.now(),
                        completed_at=datetime.now(),
                        decision_status=StoryDecision.PENDING,
                    )
                    db.add(failed_version)
                    await db.commit()
                    await push_event(version_id, "failed", {
                        "error": result.get("error", "Agent failed"),
                        "timestamp": datetime.now().isoformat(),
                    })
                    job_queue.task_done()
                    continue

                # Extract key result fields
                new_story = result.get("improved_story", state["raw_story"])
                new_ac = result.get("acceptance_criteria", [])
                final_score = float(result.get("final_score", 0.0))
                initial_score = float(result.get("initial_score", 0.0))
                testability_score = float(result.get("testability_score", 0.0))
                is_testable = result.get("is_testable", False)
                iterations = result.get("iterations", 0)
                workflow_status = result.get("workflow_status", "unknown")
                duration = result.get("duration_seconds", 0.0)
                detected_issues = result.get("testability_issues", [])

                logger.info(
                    f"Result: initial={initial_score:.3f}, final={final_score:.3f}, "
                    f"delta={final_score - initial_score:+.3f}, "
                    f"testability={testability_score:.3f}, iterations={iterations}, "
                    f"status={workflow_status}"
                )

                if detected_issues:
                    print(f"[WORKER-{worker_id}]   • Problèmes détectés:")
                    for issue in detected_issues[:3]:
                        print(f"[WORKER-{worker_id}]       → {issue}")
                
                # Vérifier si la story est trop ambiguë
                AMBIGUOUS_SCORE_THRESHOLD = 0.40
                needs_po_review = (
                    workflow_status == "garbage_input"
                    or (workflow_status == "best_effort" and initial_score < AMBIGUOUS_SCORE_THRESHOLD)
                ) 
                
                if needs_po_review:
                    print(f"\n[WORKER-{worker_id}] ⚠️ STORY TROP AMBIGUË - Notification au PO")
                    print(f"[WORKER-{worker_id}]    Raison: {workflow_status if workflow_status != 'best_effort' else f'score trop bas ({initial_score:.3f} < {AMBIGUOUS_SCORE_THRESHOLD})'}")
# 1. Poster un commentaire dans Jira
                    comment_id = await _notify_product_owner_with_suggestions(
                        db=db,
                        user_story_id=state["user_story_id"],
                        jira_id=jira_id,
                        initial_score=initial_score,
                        workflow_status=workflow_status,
                        detected_issues=detected_issues,
                        improved_story=result.get("improved_story"),
                        improved_ac=result.get("acceptance_criteria"),
                        version_id=version_id,
                    )
                    
                    if comment_id:
                        print(f"[WORKER-{worker_id}] ✅ Commentaire posté dans Jira (ID: {comment_id})")
                        print(f"[WORKER-{worker_id}]    Le PO a été invité à clarifier la story")
                    else:
                        print(f"[WORKER-{worker_id}] ❌ Échec de l'envoi du commentaire Jira")
                    
                    # 2. Créer un defect interne
                    from app.services.defect_service import create_defect
                    user_story = await get_user_story_by_id(db, state["user_story_id"])
                    jira_client = await _get_jira_client(db, state["user_story_id"])
                    
                    defect = await create_defect(
                        db=db,
                        user_story=user_story,
                        version_id=version_id,
                        detected_issues=detected_issues,
                        initial_score=initial_score,
                        workflow_status=workflow_status,
                        jira_client=jira_client,
                    )
                    
                    print(f"[WORKER-{worker_id}] 🐛 Defect créé (ID: {defect.id})")
                    
                    # 3. Notification dans l'app TestForge AI
                    await push_event(version_id, "po_notification_sent", {
                        "message": f"Le Product Owner a été notifié pour clarifier {jira_id}",
                        "jira_comment_id": comment_id,
                        "defect_id": defect.id,
                        "timestamp": datetime.now().isoformat(),
                    })
                    
                    print(f"[WORKER-{worker_id}] 📢 Notification envoyée dans l'app")
                
                # Si la story a été améliorée, proposer les changements au PO
                elif result.get("is_improved") and final_score > initial_score + 0.1:
                    print(f"\n[WORKER-{worker_id}] ✨ AMÉLIORATION PROPOSÉE")
                    print(f"[WORKER-{worker_id}]   • Gain de qualité: +{(final_score - initial_score)*100:.1f}%")
                    
                    # Proposer les changements au PO pour acceptation/refus
                    await _propose_changes_to_po(
                        db=db,
                        jira_id=jira_id,
                        original_story=state["raw_story"],
                        improved_story=result.get("improved_story"),
                        original_ac=state.get("acceptance_criteria", []),
                        improved_ac=result.get("acceptance_criteria", []),
                        version_id=version_id,
                        score_improvement=final_score - initial_score
                    )
                    
                    print(f"[WORKER-{worker_id}] 💡 Proposition envoyée au PO")
                    print(f"[WORKER-{worker_id}]    Le PO peut accepter/refuser les changements")

                # ============================================================
                # VERSIONING LOGIC
                # ============================================================
                
                # Always create a version regardless of quality
                logger.info(f"Creating new version (score={final_score:.3f})")
                version = await save_ai_version(
                    db=db,
                    version_id=version_id,
                    user_story_id=state["user_story_id"],
                    result=result,
                    state=state,
                )

                # ── TECH LEAD MODE: notify product owner + create defect ──
                needs_po_review = (
                    workflow_status == "garbage_input"
                    or (workflow_status == "best_effort" and initial_score < AMBIGUOUS_SCORE_THRESHOLD)
                )
                if needs_po_review:
                    try:
                        user_story = await get_user_story_by_id(db, state["user_story_id"])
                        detected_issues = result.get("testability_issues", [])
                        jira_client = await _get_jira_client(db, state["user_story_id"])

                        # 1. Comment on the original Jira ticket
                        comment_id = await _notify_product_owner(
                            db=db,
                            user_story=user_story,
                            jira_id=jira_id,
                            initial_score=initial_score,
                            workflow_status=workflow_status,
                            detected_issues=detected_issues,
                            version_id=version_id,
                        )

                        # 2. Create internal defect record (+ optional new Bug ticket)
                        defect = await create_defect(
                            db=db,
                            user_story=user_story,
                            version_id=version_id,
                            detected_issues=detected_issues,
                            initial_score=initial_score,
                            workflow_status=workflow_status,
                            jira_client=jira_client,
                        )

                        await push_event(version_id, "defect_created", {
                            "defect_id": defect.id,
                            "jira_issue_key": defect.jira_issue_key,
                            "jira_comment_posted": comment_id is not None,
                            "severity": defect.severity.value,
                            "message": (
                                "Story trop vague — commentaire envoyé au Product Owner"
                                + (f" sur {jira_id}" if comment_id else " (hors ligne Jira)")
                            ),
                            "timestamp": datetime.now().isoformat(),
                        })
                    except Exception as defect_exc:
                        logger.warning(f"[DEFECT] Creation failed for {version_id}: {defect_exc}")

                await push_event(version_id, "version_created", {
                    "version_id": version.id,
                    "final_score": final_score,
                    "has_new_version": True,
                    "timestamp": datetime.now().isoformat(),
                })
                
                await db.commit()
                await db.refresh(version)
                
                await push_event(version_id, "completed", {
                    "status": "completed",
                    "message": "Agent completed successfully",
                    "final_score": final_score,
                    "testability_score": testability_score,
                    "is_testable": is_testable,
                    "improved_story": new_story,
                    "acceptance_criteria": new_ac,
                    "iteration": iterations,
                    "workflow_status": workflow_status,
                    "duration": duration,
                    "version_id": version.id,
                    "has_new_version": True,
                    "timestamp": datetime.now().isoformat(),
                })
                
                logger.info(f"Version {version_id} finished successfully")
                # best = await get_best_version(db, state.get("user_story_id"))
                # best_score = best.final_score if best else 0.0

                # new_ac_normalized = normalize_ac(new_ac)
                # best_ac_normalized = (
                #     normalize_ac(best.generated_acceptance_criteria) if best else []
                # )

                # is_same_content = (
                #     best is not None
                #     and (best.improved_story or "").strip() == new_story.strip()
                #     and best_ac_normalized == new_ac_normalized
                # )

                # # CAS 1: Score worse → keep existing best
                # if best and final_score < best_score:
                #     logger.info(f"Score worse than best ({final_score:.3f} < {best_score:.3f})")
                #     await push_event(version_id, "completed", {
                #         "status": "completed",
                #         "message": "No better version found — keeping existing best",
                #         "final_score": final_score,
                #         "testability_score": testability_score,
                #         "is_testable": is_testable,
                #         "has_new_version": False,
                #         "reason": "score_worse_than_best",
                #         "best_score": best_score,
                #         "timestamp": datetime.now().isoformat(),
                #     })
                #     job_queue.task_done()
                #     continue

                # # CAS 2: Same score AND same content → no-op
                # elif best and final_score == best_score and is_same_content:
                #     logger.info("Same content as best version")
                #     await push_event(version_id, "completed", {
                #         "status": "completed",
                #         "message": "Already optimal — no better version",
                #         "final_score": final_score,
                #         "testability_score": testability_score,
                #         "is_testable": is_testable,
                #         "has_new_version": False,
                #         "reason": "already_optimal",
                #         "timestamp": datetime.now().isoformat(),
                #     })
                #     job_queue.task_done()
                #     continue

                # CAS 3: Better score or different content → create version
                # else:
                    # logger.info(f"Creating new version (score={final_score:.3f})")
                    # version = await save_ai_version(
                    #     db=db,
                    #     version_id=version_id,
                    #     user_story_id=state["user_story_id"],
                    #     result=result,
                    #     state=state,
                    # )

                    # await push_event(version_id, "version_created", {
                    #     "version_id": version.id,
                    #     "final_score": final_score,
                    #     "has_new_version": True,
                    #     "timestamp": datetime.now().isoformat(),
                    # })

                    # await db.commit()
                    # await db.refresh(version)

                    # await push_event(version_id, "completed", {
                    #     "status": "completed",
                    #     "message": "Agent completed successfully",
                    #     "final_score": final_score,
                    #     "testability_score": testability_score,
                    #     "is_testable": is_testable,
                    #     "improved_story": new_story,
                    #     "acceptance_criteria": new_ac,
                    #     "iteration": iterations,
                    #     "workflow_status": workflow_status,
                    #     "duration": duration,
                    #     "version_id": version.id,
                    #     "has_new_version": True,
                    #     "timestamp": datetime.now().isoformat(),
                    # })

                logger.info(f"Version {version_id} finished successfully")

            except TimeoutError as e:
                logger.error(f"Timeout for version {version_id}: {e}")
                if retry_count < MAX_RETRIES:
                    state["retry_count"] = retry_count + 1
                    await job_queue.put(state)
                    await push_event(version_id, "processing", {
                        "message": f"Timeout — retrying (attempt {state['retry_count']}/{MAX_RETRIES})",
                        "timestamp": datetime.now().isoformat(),
                    })
                else:
                    logger.error(f"Version {version_id} failed: timeout after {MAX_RETRIES} retries")
                    failed_version = UserStoryVersion(
                        id=version_id,
                        user_story_id=state["user_story_id"],
                        improved_story=state["raw_story"],
                        generated_acceptance_criteria=state.get("acceptance_criteria", []),
                        workflow_status=WorkflowStatus.FAILED,
                        started_at=datetime.now(),
                        completed_at=datetime.now(),
                        decision_status=StoryDecision.PENDING,
                    )
                    db.add(failed_version)
                    await db.commit()
                    await push_event(version_id, "failed", {
                        "error": f"Pipeline timeout after {MAX_RETRIES} retries",
                        "timestamp": datetime.now().isoformat(),
                    })

            except Exception as e:
                logger.error(f"Version {version_id} error: {e}", exc_info=True)
                traceback.print_exc()
                try:
                    failed_version = UserStoryVersion(
                        id=version_id,
                        user_story_id=state["user_story_id"],
                        improved_story=state["raw_story"],
                        generated_acceptance_criteria=state.get("acceptance_criteria", []),
                        workflow_status=WorkflowStatus.FAILED,
                        started_at=datetime.now(),
                        completed_at=datetime.now(),
                        decision_status=StoryDecision.PENDING,
                    )
                    db.add(failed_version)
                    await db.commit()
                except Exception as db_error:
                    logger.error(f"Failed to save error version: {db_error}")
                await push_event(version_id, "failed", {
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                })

            finally:
                job_queue.task_done()


# ============================================================
# SUBMIT / START / STOP
# ============================================================

async def submit_version(state: Dict[str, Any]) -> None:
    if not isinstance(state, dict):
        raise ValueError("State must be a dict")
    state.setdefault("acceptance_criteria", [])
    state.setdefault("language", "en")
    state.setdefault("retry_count", 0)
    _validate_state(state)
    logger.info(f"Submitting version: {state.get('version_id')}")
    await job_queue.put(state)


async def start_workers() -> None:
    global workers
    if workers:
        logger.info("Workers already started")
        return
    for i in range(MAX_WORKERS):
        task = asyncio.create_task(async_worker(i + 1))
        workers.append(task)
    logger.info(f"Started {MAX_WORKERS} workers")


async def stop_workers() -> None:
    logger.info("Stopping workers...")
    if not workers:
        return
    for _ in workers:
        await job_queue.put(None)
    await asyncio.wait_for(
        asyncio.gather(*workers, return_exceptions=True),
        timeout=30,
    )
    workers.clear()
    logger.info("All workers stopped")


async def _notify_product_owner_with_suggestions(
    db,
    user_story_id: str,
    jira_id: str,
    initial_score: float,
    workflow_status: str,
    detected_issues: List[str],
    improved_story: Optional[str],
    improved_ac: Optional[List[str]],
    version_id: str,
) -> Optional[str]:
    """Notifie le PO avec des suggestions d'amélioration"""
    
    print(f"\n[JIRA NOTIF] 📨 Préparation de la notification pour {jira_id}")
    
    jira_client = await _get_jira_client(db, user_story_id)
    if not jira_client:
        print(f"[JIRA NOTIF] ❌ Client Jira non disponible")
        return None
    
    score_pct = round(initial_score * 100, 1)
    
    # Construire le message
    paragraphs = [
        "🏗️ **TestForge AI - Analyse de qualité**",
        "",
        f"La user story *{jira_id}* a été analysée automatiquement et présente une qualité insuffisante.",
        "",
        f"📊 **Score qualité**: {score_pct}/100",
        f"📝 **Statut**: {workflow_status}",
        "",
        "**❌ Problèmes détectés:**",
    ]
    
    for issue in detected_issues[:5]:
        paragraphs.append(f"  • {issue}")
    
    if not detected_issues:
        paragraphs.append("  • Aucun détail spécifique détecté")
    
    paragraphs.extend([
        "",
        "**💡 Suggestions d'amélioration:**",
    ])
    
    if improved_story and improved_story != "?":
        # Montrer un extrait de la version améliorée
        improved_excerpt = improved_story[:300] + "..." if len(improved_story) > 300 else improved_story
        paragraphs.extend([
            "",
            "**Version améliorée proposée par l'IA:**",
            "```",
            improved_excerpt,
            "```",
            "",
            "**⚠️ Important:** Cette version ne modifie pas le contexte métier original, elle clarifie uniquement la formulation.",
            "",
            "**Actions possibles:**",
            "1. ✏️ **Accepter** - Copiez la version ci-dessus dans Jira",
            "2. 🔄 **Adapter** - Modifiez la proposition selon votre besoin",
            "3. ❌ **Refuser** - Si la version actuelle est correcte",
            "",
            f"🔗 **Voir les détails dans TestForge AI**",
        ])
    else:
        paragraphs.extend([
            "",
            "Merci d'ajouter plus de détails dans la description et les critères d'acceptation.",
            "",
            "**Exemple de bonne user story:**",
            "```",
            "En tant qu'utilisateur, je veux me connecter avec mon email et mot de passe",
            "afin d'accéder à mon compte personnel.",
            "",
            "Critères d'acceptation:",
            "- L'utilisateur peut saisir son email",
            "- L'utilisateur peut saisir son mot de passe",
            "- Un message d'erreur s'affiche si les identifiants sont incorrects",
            "- L'utilisateur est redirigé vers son tableau de bord après connexion réussie",
            "```",
        ])
    
    try:
        print(f"[JIRA NOTIF] ✉️ Envoi du commentaire vers Jira...")
        result = await jira_client.add_comment(jira_id, paragraphs)
        comment_id = result.get("id")
        print(f"[JIRA NOTIF] ✅ Commentaire envoyé (ID: {comment_id})")
        return comment_id
    except Exception as exc:
        print(f"[JIRA NOTIF] ❌ Échec: {exc}")
        return None


async def _propose_changes_to_po(
    db,
    jira_id: str,
    original_story: str,
    improved_story: str,
    original_ac: List[str],
    improved_ac: List[str],
    version_id: str,
    score_improvement: float
):
    """Propose les changements au PO pour acceptation/refus"""
    
    print(f"\n[PROPOSAL] 💡 Préparation de la proposition pour {jira_id}")
    
    jira_client = await _get_jira_client(db, None)  # À adapter
    if not jira_client:
        print(f"[PROPOSAL] ❌ Client Jira non disponible")
        return
    
    # Nettoyer les AC pour l'affichage
    original_ac_text = "\n".join(f"  • {ac}" for ac in original_ac[:3])
    improved_ac_text = "\n".join(f"  • {ac}" for ac in improved_ac[:3])
    
    paragraphs = [
        "✨ **TestForge AI - Proposition d'amélioration**",
        "",
        f"Une meilleure version de la user story *{jira_id}* a été générée automatiquement.",
        "",
        f"📈 **Gain de qualité**: +{round(score_improvement * 100, 1)}%",
        "",
        "**📝 Version originale:**",
        "```",
        original_story[:200] + "..." if len(original_story) > 200 else original_story,
        "```",
        "",
        "**✨ Version améliorée proposée:**",
        "```",
        improved_story[:200] + "..." if len(improved_story) > 200 else improved_story,
        "```",
    ]
    
    if original_ac_text and improved_ac_text:
        paragraphs.extend([
            "",
            "**Critères d'acceptation - Avant/après:**",
            "",
            "*Avant:*",
            original_ac_text,
            "",
            "*Après:*",
            improved_ac_text,
        ])
    
    paragraphs.extend([
        "",
        "---",
        f"📱 **Voir la version complète dans TestForge AI**",
        "",
        "*Note: L'IA n'a pas modifié le contexte métier, seulement clarifié la formulation.*"
    ])
    
    try:
        print(f"[PROPOSAL] ✉️ Envoi de la proposition...")
        result = await jira_client.add_comment(jira_id, paragraphs)
        print(f"[PROPOSAL] ✅ Proposition envoyée (Comment ID: {result.get('id')})")
    except Exception as e:
        print(f"[PROPOSAL] ❌ Échec: {e}")


async def _get_jira_client(db, user_story_id: str):
    """Helper pour récupérer le client Jira"""
    try:
        from app.models.user_story import UserStory
        from app.models.jira_project import JiraProject
        from app.models.jira_connection import JiraConnection
        from app.services.jira_session_manager import JiraSessionManager

        if user_story_id:
            row = await db.execute(
                select(JiraConnection)
                .join(JiraProject, JiraProject.jira_connection_id == JiraConnection.id)
                .join(UserStory, UserStory.project_id == JiraProject.id)
                .where(UserStory.id == user_story_id)
            )
            conn = row.scalar_one_or_none()
        else:
            # Fallback: prendre la première connexion active
            row = await db.execute(
                select(JiraConnection).where(JiraConnection.is_active == True)
            )
            conn = row.scalar_one_or_none()
        
        if not conn or not conn.is_active:
            return None
        
        manager = JiraSessionManager(db)
        return await manager.get_client(conn)
    except Exception as exc:
        print(f"[JIRA CLIENT] ❌ Erreur: {exc}")
        return None