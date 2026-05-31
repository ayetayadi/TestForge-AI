"""
Test case generation async worker.

Job structure (dict):
    job_id            : str   — SSE channel ID
    test_plan_id      : str   — TestPlan to generate TCs for (REQUIRED)
    test_suite_id     : str | None — TestSuite to assign TCs to (OPTIONAL)
    risk_level        : str | None
    risk_score        : float | None
    risk_description  : str | None
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

from app.core.database import async_session_maker
from app.services import test_case_service as service
from app.streaming.sse_manager import push_event
from .tc_queue import tc_job_queue
from app.core.config import settings
from app.llm.llm_control import set_worker_api_key

logger = logging.getLogger(__name__)

MAX_TC_WORKERS = settings.MAX_WORKERS
TC_WORKER_TIMEOUT = 600  # 10 min — 6 US × ~30-40s each + possible rate-limit retries
MAX_RETRIES = 3

_tc_workers: List[asyncio.Task] = []


# ============================================================
# API KEY ASSIGNMENT
# ============================================================

def _get_api_key_for_worker(worker_id: int) -> str:
    """Retourne la clé API dédiée à ce worker (1→KEY_1, 2→KEY_2, etc.)."""
    key_name = f"GROQ_API_KEY_{worker_id}"
    api_key = os.getenv(key_name, "")
    
    if not api_key:
        logger.warning(f"[TC WORKER-{worker_id}] ⚠️ {key_name} not found, using fallback")
        api_key = os.getenv("GROQ_API_KEY_4", os.getenv("GROQ_API_KEY", ""))
    
    return api_key


# ============================================================
# PROGRESS CALLBACK FACTORY
# ============================================================

def _make_progress_callback(job_id: str):
    async def cb(event_type: str, data: dict) -> None:
        await push_event(job_id, event_type, {**data, "timestamp": datetime.now().isoformat()})
    return cb


# ============================================================
# WORKER LOOP
# ============================================================

async def tc_worker(worker_id: int) -> None:
    api_key = _get_api_key_for_worker(worker_id)

    # Assigne la clé dans le ContextVar de cette tâche asyncio.
    # Chaque tâche a son propre contexte isolé — aucun risque d'écrasement entre workers.
    set_worker_api_key(api_key)

    key_preview = api_key[:15] + "..." if api_key else "NO_KEY"
    logger.info(f"[TC WORKER-{worker_id}] 🚀 Started with dedicated key: {key_preview}")
    
    while True:
        job: Dict[str, Any] = await tc_job_queue.get()

        if job is None:
            logger.info(f"[TC WORKER-{worker_id}] stop signal received")
            tc_job_queue.task_done()
            break

        job_id = job.get("job_id", "?")
        test_plan_id = job.get("test_plan_id")
        test_suite_id = job.get("test_suite_id")

        async with async_session_maker() as db:
            try:
                await push_event(job_id, "tc_processing", {
                    "message": f"[Worker {worker_id}] Starting test case generation...",
                    "test_plan_id": test_plan_id,
                    "test_suite_id": test_suite_id,
                    "timestamp": datetime.now().isoformat(),
                })

                try:
                    result = await asyncio.wait_for(
                        service.generate_test_cases_for_plan(
                            db=db,
                            test_plan_id=test_plan_id,
                            test_suite_id=test_suite_id,
                            risk_level=job.get("risk_level"),
                            risk_score=job.get("risk_score"),
                            risk_description=job.get("risk_description"),
                            progress_callback=_make_progress_callback(job_id),
                            scenario_type=job.get("scenario_type"),
                        ),
                        timeout=TC_WORKER_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    raise RuntimeError(f"Pipeline timeout after {TC_WORKER_TIMEOUT}s")

                if result.get("workflow_status") == "error":
                    raise RuntimeError(result.get("error", "Pipeline returned error"))

                await db.commit()

                coverage = result.get("coverage", {})
                suites_pct = coverage.get("suites_coverage", {}).get("coverage_pct", 0.0)
                req_pct = coverage.get("requirements_coverage", {}).get("coverage_pct", 0.0)

                logger.info(
                    "[TC WORKER-%d] plan=%s suite=%s: generated %d TCs | Suites=%.0f%% Req=%.0f%%",
                    worker_id, test_plan_id, test_suite_id or "None", result["count"],
                    suites_pct * 100, req_pct * 100,
                )

                await push_event(job_id, "tc_generated", {
                    "test_plan_id": test_plan_id,
                    "test_suite_id": test_suite_id,
                    "count": result["count"],
                    "feature_gherkin": result.get("feature_gherkin", ""),
                    "coverage": coverage,
                    "coverage_hints": result.get("coverage_hints", []),
                    "test_cases": result.get("test_cases", []),
                    "timestamp": datetime.now().isoformat(),
                })

            except Exception as exc:
                logger.error(
                    "[TC WORKER-%d] job %s failed: %s",
                    worker_id, job_id, exc, exc_info=True,
                )
                try:
                    await db.rollback()
                except Exception:
                    pass
                await push_event(job_id, "tc_failed", {
                    "test_plan_id": test_plan_id,
                    "test_suite_id": test_suite_id,
                    "error": str(exc),
                    "timestamp": datetime.now().isoformat(),
                })

            finally:
                tc_job_queue.task_done()


# ============================================================
# SUBMIT
# ============================================================

async def submit_tc_job(job: Dict[str, Any]) -> None:
    """
    Enqueue a test case generation job.

    Required fields:
        test_plan_id  : str   — TestPlan to generate TCs for

    Optional fields:
        test_suite_id  : str   — TestSuite to assign TCs to (can be None)
        job_id         : str   — SSE channel ID
        risk_level     : str
        risk_score     : float
        risk_description : str
        scenario_type  : str   — positive | negative | boundary (default: positive)
    """
    if not job.get("test_plan_id"):
        raise ValueError("test_plan_id is required")

    job.setdefault("job_id", f"{job['test_plan_id']}-{job.get('test_suite_id', 'nosuite')}")

    await tc_job_queue.put(job)
    logger.info(
        "[TC QUEUE] Submitted job %s for plan=%s suite=%s",
        job["job_id"], job["test_plan_id"], job.get("test_suite_id", "None")
    )


# ============================================================
# START / STOP
# ============================================================

async def start_tc_workers() -> None:
    global _tc_workers
    if _tc_workers:
        logger.info("[TC WORKERS] Already running")
        return
    for i in range(MAX_TC_WORKERS):
        task = asyncio.create_task(tc_worker(i + 1))
        _tc_workers.append(task)
    logger.info("[TC WORKERS] Started %d workers", MAX_TC_WORKERS)


async def stop_tc_workers() -> None:
    global _tc_workers
    if not _tc_workers:
        return
    for _ in _tc_workers:
        await tc_job_queue.put(None)
    await asyncio.wait_for(
        asyncio.gather(*_tc_workers, return_exceptions=True),
        timeout=30,
    )
    _tc_workers.clear()
    logger.info("[TC WORKERS] All stopped")