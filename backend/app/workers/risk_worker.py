"""
Risk analysis async worker.

Job structure (dict):
    job_id        : str  — identifiant SSE (= test_plan_id + "-" + user_story_id)
    test_plan_id  : str
    user_story_id : str
    issue_key     : str  (e.g. "PROJ-42")
    jira_priority : str | None
    story_points  : float | None
    components    : list[str]
    labels        : list[str]
    epic          : str | None

Resolution logic (ISTQB source selection):
    1. Cherche une UserStoryVersion avec decision_status=APPROVED
       → utilise improved_story + generated_acceptance_criteria
    2. Sinon, utilise user_story.title + description + acceptance_criteria originaux
"""

import asyncio
import json
import logging
import traceback
from datetime import datetime
from typing import Any, Dict, List

from app.core.database import async_session_maker
from app.repositories.user_story_repository import get_user_story_by_id
from app.repositories.user_story_version_repository import get_approved_version_for_risk
from app.repositories.risk_repository import RiskRepository
from app.schemas.risk_schema import RiskCreate
from app.ai_workflows.risk_analysis.pipeline import get_pipeline
from app.streaming.sse_manager import push_event
from .risk_queue import risk_job_queue

logger = logging.getLogger(__name__)

MAX_RISK_WORKERS = 2
RISK_WORKER_TIMEOUT = 120

_risk_workers: List[asyncio.Task] = []


# ============================================================
# SOURCE RESOLUTION
# ============================================================

async def _resolve_story_content(db, user_story_id: str) -> Dict[str, Any]:
    """
    Retourne le texte et les ACs à utiliser pour l'analyse de risques.
    Priorité : version approuvée + complétée → sinon US originale.
    """
    approved = await get_approved_version_for_risk(db, user_story_id)
    if approved:
        logger.info(
            f"[RISK WORKER] US {user_story_id}: using approved version {approved.id}"
        )
        return {
            "story": approved.improved_story,
            "acceptance_criteria": approved.generated_acceptance_criteria or [],
            "source": "approved_version",
            "version_id": approved.id,
        }

    story = await get_user_story_by_id(db, user_story_id)
    if not story:
        raise ValueError(f"UserStory {user_story_id} not found")

    logger.info(f"[RISK WORKER] US {user_story_id}: no approved version, using original")
    raw = f"{story.title}\n\n{story.description or ''}".strip()
    return {
        "story": raw,
        "acceptance_criteria": story.acceptance_criteria or [],
        "source": "original",
        "version_id": None,
    }


# ============================================================
# WORKER LOOP
# ============================================================

async def risk_worker(worker_id: int) -> None:
    logger.info(f"[RISK WORKER-{worker_id}] started")

    while True:
        job: Dict[str, Any] = await risk_job_queue.get()

        if job is None:
            logger.info(f"[RISK WORKER-{worker_id}] stop signal received")
            risk_job_queue.task_done()
            break

        job_id = job.get("job_id", "?")
        user_story_id = job.get("user_story_id")
        test_plan_id = job.get("test_plan_id")

        async with async_session_maker() as db:
            try:
                await push_event(job_id, "risk_processing", {
                    "message": "Resolving story content...",
                    "user_story_id": user_story_id,
                    "timestamp": datetime.now().isoformat(),
                })

                # ── STEP 1: Resolve source (approved version or original) ──
                content = await _resolve_story_content(db, user_story_id)

                await push_event(job_id, "risk_processing", {
                    "message": f"Running AI risk analysis (source: {content['source']})...",
                    "source": content["source"],
                    "timestamp": datetime.now().isoformat(),
                })

                # ── STEP 2: Run pipeline ──
                pipeline = get_pipeline()
                try:
                    result = await asyncio.wait_for(
                        pipeline.run(
                            story=content["story"],
                            acceptance_criteria=content["acceptance_criteria"],
                            jira_priority=job.get("jira_priority"),
                            story_points=job.get("story_points"),
                            components=job.get("components", []),
                            labels=job.get("labels", []),
                            epic=job.get("epic"),
                            issue_key=job.get("issue_key", "?"),
                            user_story_id=user_story_id,
                            test_plan_id=test_plan_id,
                        ),
                        timeout=RISK_WORKER_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    raise RuntimeError(f"Pipeline timeout after {RISK_WORKER_TIMEOUT}s")

                if result.get("workflow_status") == "error":
                    raise RuntimeError(result.get("error", "Pipeline returned error"))

                # ── STEP 3: Persist risk ──
                repo = RiskRepository(db)
                risk = await repo.create(RiskCreate(
                    project_id=job["project_id"],
                    test_plan_id=job.get("test_plan_id"),
                    user_story_id=user_story_id,
                    description=result["description"],
                    mitigation=result.get("mitigation", ""),
                    reasoning=result.get("reasoning", ""),
                    probability=result["probability"],
                    impact=result["impact"],
                    is_ai_generated=True,
                    is_accepted=None,
                    source=content["source"],
                    source_version_id=content["version_id"],
                    source_story_text=content["story"],
                    source_acceptance_criteria=json.dumps(content["acceptance_criteria"]),
                ))
                await db.commit()

                logger.info(
                    f"[RISK WORKER-{worker_id}] created risk {risk.id} "
                    f"P={risk.probability} I={risk.impact} "
                    f"score={risk.risk_score} level={risk.level}"
                )

                await push_event(job_id, "risk_analyzed", {
                    "risk_id": risk.id,
                    "user_story_id": user_story_id,
                    "level": risk.level,
                    "risk_score": risk.risk_score,
                    "probability": risk.probability,
                    "impact": risk.impact,
                    "source": content["source"],
                    "timestamp": datetime.now().isoformat(),
                })

            except Exception as exc:
                logger.error(
                    f"[RISK WORKER-{worker_id}] job {job_id} failed: {exc}",
                    exc_info=True,
                )
                traceback.print_exc()
                await push_event(job_id, "risk_failed", {
                    "user_story_id": user_story_id,
                    "error": str(exc),
                    "timestamp": datetime.now().isoformat(),
                })

            finally:
                risk_job_queue.task_done()


# ============================================================
# SUBMIT
# ============================================================

async def submit_risk_job(job: Dict[str, Any]) -> None:
    """
    Soumet un job d'analyse de risque dans la queue.

    Champs attendus :
        test_plan_id  : str  (obligatoire)
        user_story_id : str  (obligatoire)
        job_id        : str  (optionnel — généré si absent)
        issue_key     : str  (optionnel)
        jira_priority : str  (optionnel)
        story_points  : float (optionnel)
        components    : list[str] (optionnel)
        labels        : list[str] (optionnel)
        epic          : str  (optionnel)
    """
    if not job.get("project_id") or not job.get("user_story_id"):
        raise ValueError("project_id and user_story_id are required")

    job.setdefault("job_id", f"{job['project_id']}-{job['user_story_id']}")
    job.setdefault("components", [])
    job.setdefault("labels", [])

    await risk_job_queue.put(job)
    logger.info(f"[RISK QUEUE] Submitted job {job['job_id']}")


# ============================================================
# START / STOP
# ============================================================

async def start_risk_workers() -> None:
    global _risk_workers
    if _risk_workers:
        logger.info("[RISK WORKERS] Already running")
        return
    for i in range(MAX_RISK_WORKERS):
        task = asyncio.create_task(risk_worker(i + 1))
        _risk_workers.append(task)
    logger.info(f"[RISK WORKERS] Started {MAX_RISK_WORKERS} workers")


async def stop_risk_workers() -> None:
    global _risk_workers
    if not _risk_workers:
        return
    for _ in _risk_workers:
        await risk_job_queue.put(None)
    await asyncio.wait_for(
        asyncio.gather(*_risk_workers, return_exceptions=True),
        timeout=30,
    )
    _risk_workers.clear()
    logger.info("[RISK WORKERS] All stopped")
