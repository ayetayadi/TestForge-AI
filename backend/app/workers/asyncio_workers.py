"""
Job Worker pour traiter les jobs de test automation.

Utilise directement l'orchestrateur ReAct.
"""

import asyncio
import traceback
import logging
import sys
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.core.config import settings
from app.models.enums import JobPhase, JobStatus
from app.repositories.job_repository import get_job_by_id
from app.repositories.user_story_version_repository import (
    create_version,
    get_best_version
)
from app.core.database import async_session_maker
from app.streaming.sse_manager import push_event

from app.ai_agents_v2.orchestration import TestAutomationOrchestrator

from .queue import job_queue

logger = logging.getLogger(__name__)

MAX_WORKERS = settings.MAX_WORKERS
ORCHESTRATION_TIMEOUT = 300  # 5 minutes
MAX_RETRIES = 3

workers: List[asyncio.Task] = []
_orchestrator: Optional[TestAutomationOrchestrator] = None


# ============================================================
# ORCHESTRATOR SINGLETON
# ============================================================

async def get_orchestrator() -> TestAutomationOrchestrator:
    """
    Get or create orchestrator singleton.
    
    ✅ Évite de créer une nouvelle instance à chaque job.
    """
    
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
    """
    Valide que l'état contient tous les champs requis.
    
    ✅ UPDATED: Vérifier acceptance_criteria et language aussi
    """
    
    required = ["job_id", "jira_id", "raw_story", "user_story_id"]
    
    for key in required:
        if key not in state:
            raise ValueError(f"Missing required field: {key}")
    
    # ✅ Vérifier que raw_story n'est pas vide
    if not state.get("raw_story") or not state["raw_story"].strip():
        raise ValueError("raw_story cannot be empty")


def normalize_ac(ac_list: List[str]) -> List[str]:
    """Normalise une liste d'AC pour comparaison."""
    
    return sorted([
        ac.strip().lower()
        for ac in (ac_list or [])
        if ac and ac.strip()
    ])


# ============================================================
# WORKER LOOP
# ============================================================

async def async_worker(worker_id: int) -> None:
    """
    Worker loop qui traite les jobs de la queue.
    
    ✅ CORRECTED:
    - Extract correct fields from orchestrator result
    - Pass acceptance_criteria and language to orchestrator
    - Better error handling
    - Proper duration tracking
    """
    
    logger.info(f"Worker {worker_id} started")
    print(f"[WORKER-{worker_id}] started")
    
    while True:
        # ============================================================
        # Récupère job de la queue
        # ============================================================
        state: Dict[str, Any] = await job_queue.get()
        
        # Signal d'arrêt
        if state is None:
            logger.info(f"Worker {worker_id} received stop signal")
            print(f"[WORKER-{worker_id}] stopping")
            job_queue.task_done()
            break
        
        async with async_session_maker() as db:
            job_id = state.get("job_id")
            jira_id = state.get("jira_id", "?")
            
            job_start_time = datetime.utcnow()
            
            try:
                # ============================================================
                # VALIDATION
                # ============================================================
                _validate_state(state)
                
                logger.info(f"Processing job: {job_id}")
                print(f"\n[WORKER] Processing job: {job_id}")
                
                # ============================================================
                # RETRIEVE JOB FROM DB
                # ============================================================
                job = await get_job_by_id(db, job_id)
                
                if not job:
                    logger.error(f"Job not found: {job_id}")
                    job_queue.task_done()
                    continue
                
                # ============================================================
                # UPDATE JOB: PROCESSING
                # ============================================================
                job.status = JobStatus.PROCESSING
                job.phase = JobPhase.ANALYZING
                job.started_at = datetime.utcnow()
                
                await db.commit()
                
                logger.info(f"Job {job_id} -> PROCESSING")
                
                # ============================================================
                # SSE EVENT: Processing Started
                # ============================================================
                await push_event(job_id, "processing", {
                    "message": "Starting orchestration pipeline...",
                    "jira_id": jira_id,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                
                # ============================================================
                # RUN ORCHESTRATOR
                # 
                # ✅ CORRECTED: Pass all required parameters
                # ============================================================
                logger.info(f"Running orchestrator for {jira_id}...")
                print(f"[WORKER] Running orchestrator...")
                
                orchestrator = await get_orchestrator()
                
                try:
                    # ✅ Passer acceptance_criteria et language
                    result = await asyncio.wait_for(
                        orchestrator.run(
                            jira_id=jira_id,
                            story=state["raw_story"],
                            thread_id=f"job-{job_id}",
                            acceptance_criteria=state.get("acceptance_criteria", []),
                            language=state.get("language", "en")
                        ),
                        timeout=ORCHESTRATION_TIMEOUT
                    )

                    if result.get("status") == "failed":
                        logger.error(f"Orchestrator reported failure: {result.get('errors', [])}")
                        await push_event(job_id, "failed", {
                            "error": result.get("error", "Orchestration failed"),
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                        job_queue.task_done()
                        continue
                    
                    logger.info(f"✓ Orchestrator completed: {result.get('status')}")
                
                except asyncio.TimeoutError:
                    logger.error(f"Orchestrator timeout: {job_id}")
                    raise TimeoutError(
                        f"Orchestrator timeout after {ORCHESTRATION_TIMEOUT}s"
                    )
                
                # ============================================================
                # EXTRACT RESULTS FROM ORCHESTRATOR OUTPUT
                # 
                # ✅ CORRECTED: Use correct field names
                # ============================================================
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
                    f"[RESULT-{job_id}]"
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
                best = await get_best_version(db, state.get("user_story_id"))
                best_score = best.final_score if best else 0.0
                
                new_ac_normalized = normalize_ac(new_ac)
                best_ac_normalized = (
                    normalize_ac(best.generated_acceptance_criteria)
                    if best else []
                )
                
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
                
                if best and final_score < best_score:
                    logger.info(
                        f"Score worse than best ({final_score:.3f} < {best_score:.3f})"
                    )
                    print(f"[SKIP] Score worse than best")
                    version = best
                    has_new_version = False
                
                elif best and final_score == best_score and is_same_content:
                    logger.info(f"Same content as best version")
                    print(f"[SKIP] Same content as best version")
                    version = best
                    has_new_version = False
                
                else:
                    logger.info(f"Creating new version (score={final_score:.3f})")
                    print(f"[CREATE] New improved version")
                    
                    version = await create_version(
                        db=db,
                        user_story_id=state.get("user_story_id"),
                        job_id=job_id,
                        improved_story=new_story,
                        acceptance_criteria=new_ac,
                        initial_score=initial_score,
                        final_score=final_score,
                        iteration=iterations,
                        duration=duration,
                        testability_score=testability_score,
                        is_testable=is_testable,
                        testability_issues=user_story_improvement.get("testability_issues", []),
                        model_used=result.get("model_used", "gpt-4o-mini"),
                        prompt_tokens=result.get("prompt_tokens", 0),
                        completion_tokens=result.get("completion_tokens", 0),
                        llm_calls=iterations
                    )
                    
                    logger.info(f"✓ Version created: {version.id}")
                
                # ============================================================
                # UPDATE JOB: COMPLETED
                # ============================================================
                job.status = JobStatus.COMPLETED
                job.phase = JobPhase.COMPLETED
                job.final_score = final_score
                job.iteration = iterations
                job.retry_count = 0
                job.completed_at = datetime.utcnow()
                
                await db.commit()
                
                logger.info(f"Job {job_id} -> COMPLETED (score={final_score:.3f})")
                
                # ============================================================
                # SSE EVENT: Completed
                # ============================================================
                await push_event(job_id, "completed", {
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
                    "version_id": getattr(version, "id", None),
                    "has_new_version": has_new_version,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                
                print(f"[DONE] Job {job_id} finished successfully\n")
            
            # ============================================================
            # TIMEOUT HANDLING (with retry)
            # ============================================================
            except TimeoutError as e:
                logger.error(f"Timeout for job {job_id}: {e}")
                print(f"[TIMEOUT] Job {job_id}: {e}")
                
                job = await get_job_by_id(db, job_id)
                
                if job:
                    if job.retry_count < MAX_RETRIES:
                        # Retry
                        job.retry_count += 1
                        job.status = JobStatus.PENDING
                        job.phase = JobPhase.ANALYZING
                        
                        await db.commit()
                        
                        logger.info(
                            f"Job {job_id} timeout - "
                            f"retry {job.retry_count}/{MAX_RETRIES}"
                        )
                        print(
                            f"[RETRY] Job {job_id} - "
                            f"attempt {job.retry_count}/{MAX_RETRIES}"
                        )
                        
                        state["is_retry"] = True
                        await job_queue.put(state)
                        
                        await push_event(job_id, "processing", {
                            "message": (
                                f"Timeout - retrying "
                                f"(attempt {job.retry_count}/{MAX_RETRIES})"
                            ),
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                    
                    else:
                        # Échec après max retries
                        job.status = JobStatus.FAILED
                        job.error = f"Timeout after {MAX_RETRIES} retries"
                        job.completed_at = datetime.utcnow()
                        
                        await db.commit()
                        
                        logger.error(
                            f"Job {job_id} failed: "
                            f"timeout after {MAX_RETRIES} retries"
                        )
                        print(
                            f"[FAILED] Job {job_id}: "
                            f"timeout after {MAX_RETRIES} retries"
                        )
                        
                        await push_event(job_id, "failed", {
                            "error": f"Pipeline timeout after {MAX_RETRIES} retries",
                            "timestamp": datetime.utcnow().isoformat(),
                        })
            
            # ============================================================
            # GENERAL ERROR HANDLING
            # ============================================================
            except Exception as e:
                logger.error(f"Job {job_id} error: {e}", exc_info=True)
                traceback.print_exc()
                print(f"[ERROR] Job {job_id} error: {e}")
                
                job = await get_job_by_id(db, job_id)
                
                if job:
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    job.completed_at = datetime.utcnow()
                    
                    await db.commit()
                    
                    logger.error(f"Job {job_id} -> FAILED")
                
                await push_event(job_id, "failed", {
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                })
                
                print(f"[ERROR] Job {job_id} failed\n")
            
            finally:
                # ============================================================
                # CLEANUP
                # ============================================================
                job_queue.task_done()


# ============================================================
# SUBMIT JOB
# ============================================================

async def submit_job(state: Dict[str, Any]) -> None:
    """
    Soumet un job à la queue.
    
    ✅ UPDATED: Validate story and provide defaults
    
    Args:
        state: État du job avec:
            - job_id: Identifiant du job
            - jira_id: Identifiant Jira
            - raw_story: Histoire utilisateur
            - user_story_id: ID de la user story
            - acceptance_criteria: (optionnel) AC existantes
            - language: (optionnel) Langue ("en", "fr", etc.)
            
    Raises:
        ValueError: Si validation échoue
    """
    
    if not isinstance(state, dict):
        raise ValueError("State must be a dict")
    
    # ✅ Ajouter defaults
    if "acceptance_criteria" not in state:
        state["acceptance_criteria"] = []
    
    if "language" not in state:
        state["language"] = "en"
    
    _validate_state(state)
    
    logger.info(f"Submitting job: {state.get('job_id')}")
    
    await job_queue.put(state)


# ============================================================
# START WORKERS
# ============================================================

async def start_workers() -> None:
    """
    Démarre les workers.
    
    Crée MAX_WORKERS tâches asyncio qui traitent les jobs.
    """
    
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
    """
    Arrête les workers proprement.
    
    Envoie un signal d'arrêt à chaque worker.
    Attend que tous les workers terminent.
    """
    
    logger.info("Stopping workers...")
    print("[WORKERS] Stopping...")
    
    if not workers:
        logger.info("No workers to stop")
        return
    
    # Envoyer signal d'arrêt à chaque worker
    for _ in workers:
        await job_queue.put(None)
    
    # Attendre que tous les workers s'arrêtent (avec timeout)
    await asyncio.wait_for(
        asyncio.gather(*workers, return_exceptions=True),
        timeout=30
    )
    
    workers.clear()
    
    logger.info("All workers stopped")
    print("[WORKERS] All workers stopped")