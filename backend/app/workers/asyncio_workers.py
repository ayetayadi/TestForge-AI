import asyncio
import traceback
from typing import Dict, Any, List

from app.core.config import settings
from app.ai_agents.user_stories.pipeline.runner import run_user_story_pipeline

from app.models.enums import JobPhase, JobStatus
from app.repositories.job_repository import get_job_by_id
from app.repositories.user_story_version_repository import create_version
from app.core.database import async_session_maker
from app.streaming.sse_manager import push_event

from .queue import job_queue


MAX_WORKERS = settings.MAX_WORKERS
workers: List[asyncio.Task] = []


# =========================
# VALIDATION
# =========================
def _validate_state(state: Dict[str, Any]):
    required = ["job_id", "jira_id", "raw_story"]

    for key in required:
        if key not in state:
            raise ValueError(f"Missing required field: {key}")


# =========================
# WORKER LOOP
# =========================
async def async_worker(worker_id: int):
    print(f"[WORKER-{worker_id}] started")

    while True:
        state: Dict[str, Any] = await job_queue.get()

        if state is None:
            print(f"[WORKER-{worker_id}] stopping")
            job_queue.task_done()
            break

        async with async_session_maker() as db:
            job_id = state.get("job_id")
            
            try:
                _validate_state(state)

                job = await get_job_by_id(db, job_id)

                if not job:
                    job_queue.task_done()
                    continue

                # SET START
                job.status = JobStatus.PROCESSING
                job.phase = JobPhase.ANALYZING
                job.iteration = 0

                # RUN PIPELINE
                result = await asyncio.wait_for(
                    run_user_story_pipeline(state),
                    timeout=120
                )

                # SAVE VERSION
                print(f"[VERSION CREATE] best_story: {result.get('best_story')[:50] if result.get('best_story') else None}...")
                print(f"[VERSION CREATE] best_ac: {result.get('best_ac')}")
                print(f"[VERSION CREATE] acceptance_criteria: {result.get('acceptance_criteria')}")

                version = await create_version(
                    db=db,
                    user_story_id=state["user_story_id"],
                    job_id=job_id,
                    improved_story=result.get("best_story") or result.get("improved_story"),  
                    acceptance_criteria=result.get("best_ac") or result.get("acceptance_criteria", []), 
                    initial_score=result.get("initial_score"),
                    final_score=result.get("best_score") or result.get("final_score"), 
                    iteration=result.get("iteration", 0),
                    llm_calls=result.get("llm_calls"),
                    duration=result.get("duration"),
                )

                # COMPLETE
                job.status = JobStatus.COMPLETED
                job.phase = JobPhase.COMPLETED
                job.final_score = result.get("final_score")
                job.iteration = result.get("iteration", 0)

                await db.commit()

                await push_event(job_id, "completed", {
                    "final_score": result.get("best_score") or result.get("final_score"), 
                    "initial_score": result.get("initial_score"),
                    "improved_story": result.get("best_story") or result.get("improved_story"),
                    "acceptance_criteria": result.get("best_ac") or result.get("acceptance_criteria", []),
                    "iteration": result.get("iteration", 0),
                    "version_id": version.id if version else None,
                })
                
                print(f"[WORKER-{worker_id}] ✅ Job {job_id} completed, SSE pushed")

            except asyncio.TimeoutError:
                job = await get_job_by_id(db, state["job_id"])
                if job:
                    job.status = JobStatus.FAILED
                    job.error = "Timeout"
                    await db.commit()
                
                # ✅ PUSH SSE FAILED EVENT
                await push_event(job_id, "failed", {
                    "error": "Pipeline timeout"
                })

            except Exception as e:
                traceback.print_exc()

                job = await get_job_by_id(db, state["job_id"])
                if job:
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    await db.commit()

                # ✅ PUSH SSE FAILED EVENT
                await push_event(job_id, "failed", {
                    "error": str(e)
                })

            finally:
                job_queue.task_done()


# =========================================================
# SUBMIT JOB
# =========================================================
async def submit_job(state: Dict[str, Any]):
    if not isinstance(state, dict):
        raise ValueError("State must be a dict")

    if not state.get("raw_story") or not state["raw_story"].strip():
        print(f"[BLOCKED] Empty raw_story for {state.get('jira_id')}")
        return

    _validate_state(state)

    await job_queue.put(state)


# =========================================================
# START WORKERS
# =========================================================
async def start_workers():
    global workers

    if workers:
        print("[WORKERS] Already started")
        return

    for i in range(MAX_WORKERS):
        task = asyncio.create_task(async_worker(i + 1))
        workers.append(task)

    print(f"[WORKERS] Started {MAX_WORKERS} workers")


# =========================================================
# STOP WORKERS
# =========================================================
async def stop_workers():
    print("[WORKERS] Stopping...")

    # envoyer signal stop
    for _ in workers:
        await job_queue.put(None)

    await asyncio.gather(*workers, return_exceptions=True)

    workers.clear()

    print("[WORKERS] All workers stopped")