import asyncio
import traceback
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.models.enums import AgentStatus, StoryDecision
from app.repositories.user_story_version_repository import (
    get_best_version,
)
from app.repositories.user_story_repository import get_user_story_by_id

from app.core.config import settings
from app.core.database import async_session_maker
from app.streaming.sse_manager import push_event

from app.ai_agents_v2.orchestration import TestAutomationOrchestrator
from app.models.user_story_version import UserStoryVersion

from .queue import job_queue

logger = logging.getLogger(__name__)

MAX_WORKERS = settings.MAX_WORKERS
ORCHESTRATION_TIMEOUT = 120  # 2 minutes
MAX_RETRIES = 3

workers: List[asyncio.Task] = []
_orchestrator: Optional[TestAutomationOrchestrator] = None


# ============================================================
# ORCHESTRATOR SINGLETON
# ============================================================

async def get_orchestrator() -> TestAutomationOrchestrator:
    global _orchestrator
    
    if _orchestrator is None:
        logger.info("Creating orchestrator singleton...")
        _orchestrator = TestAutomationOrchestrator()
        logger.info("✓ Orchestrator singleton created")
    
    return _orchestrator


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
    """Normalise une liste d'AC pour comparaison."""
    
    return sorted([
        ac.strip().lower()
        for ac in (ac_list or [])
        if ac and ac.strip()
    ])


async def save_ai_version(
    db,
    version_id: str,
    user_story_id: str,
    result: Dict[str, Any],
    state: Dict[str, Any]
) -> UserStoryVersion:
    """Sauvegarde la version - SANS commit (le caller le fera)"""
    
    user_story_improvement = result.get("user_story_improvement", {})
    
    # Extraire les résultats
    improved_story = user_story_improvement.get(
        "improved_story", 
        state["raw_story"]
    )
    generated_ac = user_story_improvement.get(
        "acceptance_criteria", 
        state.get("acceptance_criteria", [])
    )
    initial_score = float(user_story_improvement.get("initial_score", 0.0))
    final_score = float(user_story_improvement.get("final_score", 0.0))
    testability_score = float(user_story_improvement.get("testability_score", 0.0))
    is_testable = user_story_improvement.get("is_testable", False)
    testability_issues = user_story_improvement.get("testability_issues", [])
    iterations = user_story_improvement.get("iterations", 0)
    duration = user_story_improvement.get("duration_seconds", 0.0)
    agent_status_value = user_story_improvement.get("agent_status", "completed")
    
    # Convertir le statut
    if agent_status_value == "completed":
        agent_status = AgentStatus.COMPLETED
    elif agent_status_value == "failed":
        agent_status = AgentStatus.FAILED
    else:
        agent_status = AgentStatus.COMPLETED
    
    # Créer la version
    version = UserStoryVersion(
        id=version_id,
        user_story_id=user_story_id,
        improved_story=improved_story,
        generated_acceptance_criteria=generated_ac,
        initial_score=initial_score,
        final_score=final_score,
        testability_score=testability_score,
        is_testable=is_testable,
        testability_issues=testability_issues,
        llm_calls=iterations,
        duration=duration,
        model_used=result.get("model_used", "unknown"),
        prompt_tokens=result.get("prompt_tokens", 0),
        completion_tokens=result.get("completion_tokens", 0),
        agent_status=agent_status,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow() if agent_status == AgentStatus.COMPLETED else None,
        decision_status=StoryDecision.PENDING,
    )
    
    db.add(version)
    await db.flush()  # ← seulement flush, pas commit
    
    # Mettre à jour le score courant de la story
    story = await get_user_story_by_id(db, user_story_id)
    if story:
        story.current_score = final_score
        await db.flush()
    
    print(f"[VERSION] Created version {version.id} with score {final_score:.3f}")
    logger.info(f"Version created: {version.id}, score={final_score:.3f}")
    
    return version


# ============================================================
# WORKER LOOP
# ============================================================

async def async_worker(worker_id: int) -> None:
    logger.info(f"Worker {worker_id} started")
    print(f"[WORKER-{worker_id}] started")
    
    while True:
        state: Dict[str, Any] = await job_queue.get()
        
        if state is None:
            logger.info(f"Worker {worker_id} received stop signal")
            print(f"[WORKER-{worker_id}] stopping")
            job_queue.task_done()
            break
        
        async with async_session_maker() as db:
            version_id = state.get("version_id")
            jira_id = state.get("jira_id", "?")
            retry_count = state.get("retry_count", 0)
            
            try:
                _validate_state(state)
                
                logger.info(f"Processing version: {version_id} (Jira: {jira_id}, retry: {retry_count})")
                print(f"\n[WORKER] Processing version: {version_id}")

                await push_event(version_id, "processing", {
                    "message": "Starting orchestration pipeline...",
                    "jira_id": jira_id,
                    "version_id": version_id,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                
                logger.info(f"Running orchestrator for {jira_id}...")
                print(f"[WORKER] Running orchestrator...")
                
                orchestrator = await get_orchestrator()
                
                try:
                    result = await asyncio.wait_for(
                        orchestrator.run(
                            jira_id=jira_id,
                            story=state["raw_story"],
                            thread_id=f"version-{version_id}",
                            acceptance_criteria=state.get("acceptance_criteria", []),
                            language=state.get("language", "en")
                        ),
                        timeout=ORCHESTRATION_TIMEOUT
                    )

                    if result.get("status") == "failed":
                        logger.error(f"Orchestrator reported failure: {result.get('errors', [])}")
                        failed_version = UserStoryVersion(
                            id=version_id,
                            user_story_id=state["user_story_id"],
                            improved_story=state["raw_story"],
                            generated_acceptance_criteria=state.get("acceptance_criteria", []),
                            agent_status=AgentStatus.FAILED,
                            started_at=datetime.utcnow(),
                            completed_at=datetime.utcnow(),
                            decision_status=StoryDecision.PENDING,
                        )
                        db.add(failed_version)
                        await db.commit()
                        await push_event(version_id, "failed", {
                            "error": result.get("error", "Orchestration failed"),
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                        job_queue.task_done()
                        continue
                    
                    logger.info(f"✓ Orchestrator completed: {result.get('status')}")
                
                except asyncio.TimeoutError:
                    logger.error(f"Orchestrator timeout: {version_id}")
                    raise TimeoutError(
                        f"Orchestrator timeout after {ORCHESTRATION_TIMEOUT}s"
                    )

                user_story_improvement = result.get("user_story_improvement", {})
                
                new_story = user_story_improvement.get(
                    "improved_story",
                    state["raw_story"]
                )
                new_ac = user_story_improvement.get("acceptance_criteria", [])
                
                final_score = float(user_story_improvement.get("final_score", 0.0))
                initial_score = float(user_story_improvement.get("initial_score", 0.0))
                
                testability_score = float(
                    user_story_improvement.get("testability_score", 0.0)
                )
                is_testable = user_story_improvement.get("is_testable", False)
                iterations = user_story_improvement.get("iterations", 0)
                agent_status = user_story_improvement.get("agent_status", "unknown")
                duration = user_story_improvement.get("duration_seconds", 0.0)
                                
                logger.info(
                    f"Results: initial={initial_score:.3f}, final={final_score:.3f}, "
                    f"delta={final_score - initial_score:+.3f}, "
                    f"ac_count={len(new_ac)}, "
                    f"testability={testability_score:.3f}, "
                    f"iterations={iterations}, "
                    f"agent_status={agent_status}, "
                    f"duration={duration:.1f}s"
                )
                
                print(
                    f"[RESULT-{version_id}]"
                    f" initial={initial_score:.3f}, final={final_score:.3f}, delta={final_score - initial_score:+.3f}"
                    f" | testability={testability_score:.3f}"
                    f" | ac={len(new_ac)}"
                    f" | iterations={iterations}"
                    f" | duration={duration:.1f}s"
                    f" | status={agent_status}"
                )
                
                # ============================================================
                # VERSIONING LOGIC
                # ============================================================
                # 1. Récupérer la meilleure version existante
                best = await get_best_version(db, state.get("user_story_id"))
                best_score = best.final_score if best else 0.0
                
                # 2. Normaliser les critères d'acceptation pour comparaison
                new_ac_normalized = normalize_ac(new_ac)
                best_ac_normalized = (
                    normalize_ac(best.generated_acceptance_criteria)
                    if best else []
                )
                
                # 3. Vérifier si le contenu est identique
                is_same_content = (
                    best is not None
                    and (best.improved_story or "").strip() == new_story.strip()
                    and best_ac_normalized == new_ac_normalized
                )
                
                # ============================================================
                # DECISION: Créer nouvelle version ou réutiliser meilleure
                # ============================================================
                has_new_version = True
                version = None
                
                # CAS 1: Score moins bon → PAS de création
                if best and final_score < best_score:
                    logger.info(
                        f"Score worse than best ({final_score:.3f} < {best_score:.3f})"
                    )
                    print(f"[SKIP] Score worse than best")
                    version = best
                    has_new_version = False

                    await push_event(version_id, "completed", {
                        "status": "completed",
                        "message": "No better version found - keeping existing best version",
                        "final_score": final_score,
                        "testability_score": testability_score,
                        "is_testable": is_testable,
                        "has_new_version": False,
                        "reason": "score_worse_than_best",
                        "best_score": best_score,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    
                    print(f"[DONE] No new version created (score {final_score:.3f} < best {best_score:.3f})\n")
                    job_queue.task_done()
                    continue
                
                # CAS 2: Score égal ET contenu identique → PAS de création
                elif best and final_score == best_score and is_same_content:
                    logger.info(f"Same content as best version")
                    print(f"[SKIP] Same content as best version")
                    version = best
                    has_new_version = False

                    await push_event(version_id, "completed", {
                        "status": "completed",
                        "message": "Already optimal - no better version",
                        "final_score": final_score,
                        "testability_score": testability_score,
                        "is_testable": is_testable,
                        "has_new_version": False,
                        "reason": "already_optimal",
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    
                    print(f"[DONE] No new version created (same content as best)\n")
                    job_queue.task_done()
                    continue

                # CAS 3: Score meilleur OU score égal mais contenu différent → CRÉATIO
                else:
                    logger.info(f"Creating new version (score={final_score:.3f})")
                    print(f"[CREATE] New improved version")
                    
                    version = await save_ai_version(
                        db=db,
                        version_id=version_id,
                        user_story_id=state["user_story_id"],
                        result=result,
                        state=state
                    )
                    
                    logger.info(f"✓ Version created: {version.id}")

                    await push_event(version_id, "version_created", {
                        "version_id": version.id,
                        "final_score": final_score,
                        "has_new_version": True,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                
                # Commit final
                await db.commit()
                
                # Rafraîchir si nécessaire
                if has_new_version and version:
                    await db.refresh(version)

                await push_event(version_id, "completed", {
                    "status": "completed",
                    "message": "Orchestration completed successfully",
                    "final_score": final_score,
                    "testability_score": testability_score,
                    "is_testable": is_testable,
                    "improved_story": new_story,
                    "acceptance_criteria": new_ac,
                    "iteration": iterations,
                    "agent_status": agent_status,
                    "duration": duration,
                    "version_id": version.id,
                    "has_new_version": has_new_version,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                
                print(f"[DONE] Version {version_id} finished successfully\n")
            
            # ============================================================
            # TIMEOUT HANDLING (with retry)
            # ============================================================
            except TimeoutError as e:
                logger.error(f"Timeout for version {version_id}: {e}")
                print(f"[TIMEOUT] Version {version_id}: {e}")
                
                if retry_count < MAX_RETRIES:
                    new_retry_count = retry_count + 1
                    state["retry_count"] = new_retry_count
                    
                    logger.info(
                        f"Version {version_id} timeout - "
                        f"retry {new_retry_count}/{MAX_RETRIES}"
                    )
                    print(
                        f"[RETRY] Version {version_id} - "
                        f"attempt {new_retry_count}/{MAX_RETRIES}"
                    )
                    
                    await job_queue.put(state)
                    
                    await push_event(version_id, "processing", {
                        "message": (
                            f"Timeout - retrying "
                            f"(attempt {new_retry_count}/{MAX_RETRIES})"
                        ),
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    
                else:                    
                    logger.error(
                        f"Version {version_id} failed: "
                        f"timeout after {MAX_RETRIES} retries"
                    )
                    failed_version = UserStoryVersion(
                        id=version_id,
                        user_story_id=state["user_story_id"],
                        improved_story=state["raw_story"],
                        generated_acceptance_criteria=state.get("acceptance_criteria", []),
                        agent_status=AgentStatus.FAILED,
                        started_at=datetime.utcnow(),
                        completed_at=datetime.utcnow(),
                        decision_status=StoryDecision.PENDING,
                    )
                    db.add(failed_version)
                    await db.commit()

                    await push_event(version_id, "failed", {
                        "error": f"Pipeline timeout after {MAX_RETRIES} retries",
                        "timestamp": datetime.utcnow().isoformat(),
                    })
            
            # ============================================================
            # GENERAL ERROR HANDLING
            # ============================================================
            except Exception as e:
                logger.error(f"Version {version_id} error: {e}", exc_info=True)
                traceback.print_exc()
                print(f"[ERROR] Version {version_id} error: {e}")
                
                try:
                    failed_version = UserStoryVersion(
                        id=version_id,
                        user_story_id=state["user_story_id"],
                        improved_story=state["raw_story"],
                        generated_acceptance_criteria=state.get("acceptance_criteria", []),
                        agent_status=AgentStatus.FAILED,
                        started_at=datetime.utcnow(),
                        completed_at=datetime.utcnow(),
                        decision_status=StoryDecision.PENDING,
                    )
                    db.add(failed_version)
                    await db.commit()
                except Exception as db_error:
                    logger.error(f"Failed to save error version: {db_error}")
                
                await push_event(version_id, "failed", {
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                })
                
                print(f"[ERROR] Version {version_id} failed\n")
            
            finally:
                job_queue.task_done()


# ============================================================
# SUBMIT VERSION
# ============================================================

async def submit_version(state: Dict[str, Any]) -> None:
    """Soumet une version à la queue"""
    
    if not isinstance(state, dict):
        raise ValueError("State must be a dict")
    
    if "acceptance_criteria" not in state:
        state["acceptance_criteria"] = []
    
    if "language" not in state:
        state["language"] = "en"

    if "retry_count" not in state:
        state["retry_count"] = 0
    
    _validate_state(state)
    
    logger.info(f"Submitting version: {state.get('version_id')}")
    
    await job_queue.put(state)


# ============================================================
# START WORKERS
# ============================================================

async def start_workers() -> None:
    global workers
    
    if workers:
        logger.info("Workers already started")
        print("[WORKERS] Already started")
        return
    
    for i in range(MAX_WORKERS):
        task = asyncio.create_task(async_worker(i + 1))
        workers.append(task)
    
    logger.info(f"Started {MAX_WORKERS} workers")
    print(f"[WORKERS] Started {MAX_WORKERS} workers")


# ============================================================
# STOP WORKERS
# ============================================================

async def stop_workers() -> None:
    """Arrête les workers proprement."""
    
    logger.info("Stopping workers...")
    print("[WORKERS] Stopping...")
    
    if not workers:
        logger.info("No workers to stop")
        return
    
    for _ in workers:
        await job_queue.put(None)
    
    await asyncio.wait_for(
        asyncio.gather(*workers, return_exceptions=True),
        timeout=30
    )
    
    workers.clear()
    
    logger.info("All workers stopped")
    print("[WORKERS] All workers stopped")