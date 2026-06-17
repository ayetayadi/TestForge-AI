"""
Risk analysis async worker - LLM-Based (Risk Based Testing).

Architecture:
  - Each worker has its OWN LLM model instance
  - Workers process jobs asynchronously from a shared queue
  - User triggers analysis by project/sprint/epic filters
  - Each User Story gets its own Risk assessment
  - User can modify P and I after analysis via human correction endpoint
  - PRIORITY: Approved version > Original story (always check approved first)

Flow:
  1. User clicks "Analyze" with filters (project/sprint/epic)
  2. API fetches matching User Stories
  3. Jobs are submitted to queue (one per User Story)
  4. Workers pick up jobs asynchronously
  5. Each worker runs LLM analysis independently
  6. Results are persisted as Risk records
  7. SSE events push real-time progress to frontend
  8. User can review and manually correct P/I if needed
"""

import asyncio
import json
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.database import async_session_maker
from app.repositories.user_story_repository import get_user_story_by_id
from app.repositories.user_story_version_repository import get_approved_version_for_risk
from app.repositories.risk_repository import RiskRepository
from app.schemas.risk_schema import RiskCreate
from app.ai_workflows.risk_analysis.ml.pipeline import (
    RiskAnalysisPipeline,
    get_pipeline,
)
from app.streaming.sse_manager import push_event
from .risk_queue import risk_job_queue
from app.core.config import settings
from app.llm.llm_control import set_worker_api_key

logger = logging.getLogger(__name__)


MAX_RISK_WORKERS = settings.MAX_WORKERS
RISK_WORKER_TIMEOUT = 120

_risk_workers: List[asyncio.Task] = []


# ============================================================
# WORKER CLASS (Each worker owns its LLM pipeline)
# ============================================================

class RiskAnalysisWorker:
    """
    Individual worker that processes risk analysis jobs.
    
    Each worker instantiates its OWN LLM pipeline to avoid
    shared state and enable true parallel processing.
    """
    
    def __init__(self, worker_id: int):
        self.worker_id = worker_id
        self.pipeline: Optional[RiskAnalysisPipeline] = None
        self.jobs_processed: int = 0
        self.jobs_failed: int = 0
        self.started_at: Optional[datetime] = None
    
    async def initialize(self) -> None:
        """Initialize the worker's ML risk pipeline (KNN + LLM explainer)."""
        self.pipeline = await get_pipeline()
        self.started_at = datetime.now(timezone.utc)
        logger.info(
            f"[WORKER-{self.worker_id}] Initialized with ML risk pipeline "
            f"(ml_trained={self.pipeline.ml_model.is_trained if self.pipeline else False})"
        )
    
    async def process_job(self, job: Dict[str, Any]) -> None:
        """
        Process a single risk analysis job.
        
        Steps:
          1. Resolve story content (approved version PRIORITY, fallback to original)
          2. Run LLM pipeline (P: 1-5, I: 1-5)
          3. Persist Risk record
          4. Send SSE events for real-time feedback
        """
        job_id = job.get("job_id", "?")
        user_story_id = job.get("user_story_id")
        project_id = job.get("project_id")
        test_plan_id = job.get("test_plan_id")
        issue_key = job.get("issue_key", "?")
        
        async with async_session_maker() as db:
            try:
                # ── NOTIFY: Job started ──
                await self._notify(job_id, "risk_processing", {
                    "status": "started",
                    "worker_id": self.worker_id,
                    "message": f"Worker {self.worker_id} starting analysis...",
                    "user_story_id": user_story_id,
                    "issue_key": issue_key,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                # ── STEP 1: Resolve story content ──
                await self._notify(job_id, "risk_processing", {
                    "status": "resolving",
                    "message": "Resolving story content (checking approved version first)...",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                
                # ✅ TOUJOURS chercher la version approuvée en premier
                content = await self._resolve_story_content(db, user_story_id)
                
                await self._notify(job_id, "risk_processing", {
                    "status": "analyzing",
                    "message": f"Running LLM analysis (source: {content['source']})...",
                    "source": content["source"],
                    "acceptance_criteria_count": len(content["acceptance_criteria"]),
                    "story_length": len(content["story"]),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                # ── STEP 2: Run ML Pipeline (KNN for P/I + LLM explainer) ──
                try:
                    result = await asyncio.wait_for(
                        self.pipeline.run(
                            user_story=content["story"],
                            acceptance_criteria=content["acceptance_criteria"],
                            user_story_id=user_story_id,
                            test_plan_id=test_plan_id,
                        ),
                        timeout=RISK_WORKER_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    raise RuntimeError(
                        f"Risk pipeline timed out after {RISK_WORKER_TIMEOUT}s"
                    )

                if result.workflow_status == "error":
                    raise RuntimeError(
                        result.error or "Risk pipeline returned error"
                    )

                logger.info(
                    f"[WORKER-{self.worker_id}] {issue_key} → "
                    f"P={result.probability} I={result.impact} "
                    f"src={result.source} conf={result.ml_confidence}"
                )

                # ── STEP 3: Persist Risk ──

                await self._notify(job_id, "risk_processing", {
                    "status": "persisting",
                    "message": "Saving risk scenario...",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })


                # test_depth is a plain string from the ML pipeline
                valid_depths = ["comprehensive", "thorough", "standard", "smoke"]
                test_depth_value = result.test_depth or "standard"
                test_depth_value = test_depth_value if test_depth_value in valid_depths else "standard"

                repo = RiskRepository(db)
                risk = await repo.create(RiskCreate(
                    user_story_id=user_story_id,
                    test_plan_id=test_plan_id,
                    description=result.description,
                    mitigation=result.mitigation,
                    reasoning=result.reasoning,
                    probability=result.probability,          # 1-5 (KNN)
                    impact=result.impact,                    # 1-5 (KNN)
                    probability_factors=result.probability_factors,
                    impact_factors=result.impact_factors,
                    probability_reasoning=result.probability_reasoning,
                    impact_reasoning=result.impact_reasoning,
                    test_depth=test_depth_value,
                    is_ai_generated=True,
                    is_accepted=None,
                    source=content["source"],
                    source_version_id=content.get("version_id"),
                    source_story_text=content["story"],
                    source_acceptance_criteria=json.dumps(content["acceptance_criteria"]),
                ))
                await db.commit()
                self.jobs_processed += 1

                logger.info(
                    f"[WORKER-{self.worker_id}] ✅ 1 risk created "
                    f"for {issue_key} | Source={content['source']} "
                    f"(jobs: {self.jobs_processed} ok, {self.jobs_failed} failed)"
                )

                # ── NOTIFY: Complete ──
                await self._notify(job_id, "risk_analyzed", {
                    "status": "completed",
                    "worker_id": self.worker_id,
                    "user_story_id": user_story_id,
                    "issue_key": issue_key,
                    "risk_count": 1,
                    "risks": [
                        {
                            "risk_id": risk.id,
                            "level": risk.level,
                            "risk_score": risk.risk_score,
                            "probability": risk.probability,
                            "impact": risk.impact,
                            "description": risk.description,
                            "mitigation": risk.mitigation,
                            "test_depth": risk.test_depth,
                        }
                    ],
                    "source": content["source"],
                    "can_modify": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            except Exception as exc:
                # Increment failure counter
                self.jobs_failed += 1
                
                logger.error(
                    f"[WORKER-{self.worker_id}] ❌ Job {job_id} failed: {exc}",
                    exc_info=True,
                )
                
                await self._notify(job_id, "risk_failed", {
                    "status": "failed",
                    "worker_id": self.worker_id,
                    "user_story_id": user_story_id,
                    "issue_key": issue_key,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "can_retry": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

    # ── PRIVATE HELPERS ──
    
    async def _notify(self, job_id: str, event_type: str, data: dict) -> None:
        """Send SSE event to frontend."""
        try:
            await push_event(job_id, event_type, data)
        except Exception as e:
            logger.warning(f"[WORKER-{self.worker_id}] SSE push failed: {e}")
    
    # ✅ CORRIGÉ : TOUJOURS priorité à la version approuvée
    async def _resolve_story_content(
        self,
        db,
        user_story_id: str,
    ) -> Dict[str, Any]:
        """
        Resolve story text and acceptance criteria.
        
        Priority:
          1. ✅ Approved version (if exists) — ALWAYS CHECKED FIRST
          2. Original user story (fallback)
        """
        # ✅ Étape 1 : Toujours chercher la version approuvée d'abord
        approved = await get_approved_version_for_risk(db, user_story_id)
        if approved:
            logger.info(
                f"[WORKER-{self.worker_id}] US {user_story_id}: "
                f"✅ USING APPROVED VERSION {approved.id}"
            )
            return {
                "story": approved.improved_story,
                "acceptance_criteria": approved.generated_acceptance_criteria or [],
                "source": "approved_version",
                "version_id": approved.id,
            }
        
        # ✅ Étape 2 : Fallback à l'originale
        logger.info(
            f"[WORKER-{self.worker_id}] US {user_story_id}: "
            f"no approved version found, using original story"
        )
        
        story = await get_user_story_by_id(db, user_story_id)
        if not story:
            raise ValueError(f"UserStory {user_story_id} not found")
        
        story_text = f"{story.title}\n\n{story.description or ''}".strip()
        
        logger.info(
            f"[WORKER-{self.worker_id}] US {user_story_id}: "
            f"using original story ({len(story.acceptance_criteria or [])} ACs)"
        )
        
        return {
            "story": story_text,
            "acceptance_criteria": story.acceptance_criteria or [],
            "source": "original",
            "version_id": None,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get worker statistics."""
        uptime = None
        if self.started_at:
            uptime = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        
        return {
            "worker_id": self.worker_id,
            "jobs_processed": self.jobs_processed,
            "jobs_failed": self.jobs_failed,
            "success_rate": (
                round(self.jobs_processed / (self.jobs_processed + self.jobs_failed) * 100, 1)
                if (self.jobs_processed + self.jobs_failed) > 0
                else 0
            ),
            "uptime_seconds": uptime,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }


# ============================================================
# WORKER POOL
# ============================================================

_worker_instances: List[RiskAnalysisWorker] = []


def _get_api_key_for_worker(worker_id: int) -> str:
    """Retourne la clé API dédiée à ce worker (1→KEY_1, 2→KEY_2, etc.)."""
    key_name = f"GROQ_API_KEY_{worker_id}"
    api_key = os.getenv(key_name, "")
    if not api_key:
        logger.warning(f"[RISK WORKER-{worker_id}] ⚠️ {key_name} not found, using fallback")
        api_key = os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY", ""))
    return api_key


async def _run_worker(worker: RiskAnalysisWorker) -> None:
    """Main loop for a single worker."""
    api_key = _get_api_key_for_worker(worker.worker_id)
    # Assigne la clé dans le ContextVar de cette tâche asyncio.
    # Doit être fait AVANT initialize() qui crée le pipeline LLM.
    set_worker_api_key(api_key)
    key_preview = api_key[:15] + "..." if api_key else "NO_KEY"
    logger.info(f"[RISK WORKER-{worker.worker_id}] 🚀 Started with dedicated key: {key_preview}")

    await worker.initialize()

    while True:
        job: Dict[str, Any] = await risk_job_queue.get()
        
        if job is None:
            logger.info(
                f"[WORKER-{worker.worker_id}] Stop signal received "
                f"(processed: {worker.jobs_processed}, failed: {worker.jobs_failed})"
            )
            risk_job_queue.task_done()
            break
        
        await worker.process_job(job)
        risk_job_queue.task_done()


# ============================================================
# SUBMIT JOB
# ============================================================

async def submit_risk_job(job: Dict[str, Any]) -> None:
    """
    Submit a risk analysis job to the queue.
    
    Required fields:
        project_id    : str   — Project context
        user_story_id : str   — DB ID of the user story
    
    Optional fields:
        job_id        : str   — Auto-generated if not provided
        test_plan_id  : str   — Link to test plan
        issue_key     : str   — Jira key (e.g., "PROJ-42")
        story_title   : str   — Title of the user story
        story_description : str — Description of the user story
        acceptance_criteria : list[str] — Original ACs
    """
    if not job.get("project_id") or not job.get("user_story_id"):
        raise ValueError("project_id and user_story_id are required")
    
    job.setdefault("job_id", f"{job['project_id']}-{job['user_story_id']}")
    job.setdefault("test_plan_id", None)
    job.setdefault("issue_key", "?")
    job.setdefault("acceptance_criteria", [])
    
    await risk_job_queue.put(job)
    logger.info(
        f"[RISK QUEUE] Submitted job {job['job_id']} "
        f"for US {job.get('issue_key', job['user_story_id'])} "
        f"(queue size: {risk_job_queue.qsize()})"
    )


# ============================================================
# START / STOP
# ============================================================

async def start_risk_workers() -> None:
    """Start all risk analysis workers."""
    global _risk_workers, _worker_instances
    
    if _risk_workers:
        logger.info("[RISK WORKERS] Already running")
        return
    
    logger.info(f"[RISK WORKERS] Starting {MAX_RISK_WORKERS} workers...")
    
    for i in range(MAX_RISK_WORKERS):
        worker = RiskAnalysisWorker(worker_id=i + 1)
        _worker_instances.append(worker)
        task = asyncio.create_task(_run_worker(worker))
        _risk_workers.append(task)
    
    logger.info(f"[RISK WORKERS] {MAX_RISK_WORKERS} workers started")


async def stop_risk_workers() -> None:
    """Gracefully stop all risk analysis workers."""
    global _risk_workers, _worker_instances
    
    if not _risk_workers:
        return
    
    logger.info("[RISK WORKERS] Stopping all workers...")
    
    for worker in _worker_instances:
        stats = worker.get_stats()
        logger.info(
            f"[WORKER-{worker.worker_id}] Stats: "
            f"processed={stats['jobs_processed']}, "
            f"failed={stats['jobs_failed']}, "
            f"success_rate={stats['success_rate']}%"
        )
    
    for _ in _risk_workers:
        await risk_job_queue.put(None)
    
    try:
        await asyncio.wait_for(
            asyncio.gather(*_risk_workers, return_exceptions=True),
            timeout=30,
        )
    except asyncio.TimeoutError:
        logger.warning("[RISK WORKERS] Timeout waiting for workers to stop")
    
    _risk_workers.clear()
    _worker_instances.clear()
    logger.info("[RISK WORKERS] All stopped")


async def get_worker_stats() -> List[Dict[str, Any]]:
    """Get statistics for all workers."""
    return [w.get_stats() for w in _worker_instances]