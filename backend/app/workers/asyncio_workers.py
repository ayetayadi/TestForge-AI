import asyncio
import traceback
from typing import Dict, Any, List

from app.core.config import settings
from app.ai_agents.user_stories.pipeline.runner import run_user_story_pipeline

from app.models.enums import JobPhase, JobStatus
from app.repositories.job_repository import get_job_by_id
from app.repositories.user_story_version_repository import create_version, get_best_version
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

def normalize_ac(ac_list):
    return sorted([
        ac.strip().lower()
        for ac in (ac_list or [])
        if ac and ac.strip()
    ])

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

                # =========================
                # START → ANALYZING
                # =========================
                is_retry = state.get("is_retry", False)
                job.status = JobStatus.PROCESSING
                job.phase = JobPhase.ANALYZING
                job.iteration = 0

                await push_event(job_id, "analyzing")

                # =========================
                # RUN PIPELINE
                # =========================
                result = await asyncio.wait_for(
                    run_user_story_pipeline(state, resume=is_retry),
                    timeout=120
                )

                # =========================
                # EVALUATING
                # =========================
                job.phase = JobPhase.EVALUATING
                await push_event(job_id, "evaluating")

                # =========================
                # EXTRACTION
                # =========================
                new_story = (
                    result.get("best_story")
                    or result.get("improved_story")
                    or state.get("raw_story")
                )

                new_ac = result.get("best_ac") or result.get("acceptance_criteria", [])

                new_score = (
                    result.get("best_score")
                    or result.get("final_score")
                    or 0.0
                )

                initial_score = result.get("initial_score") or new_score

                duration = (
                    result.get("timing", {}).get("analysis")
                    or result.get("duration")
                )

                print(f"[RESULT] score={new_score}")

                # =========================
                # VERSIONING LOGIC (PROD)
                # =========================
                best = await get_best_version(db, state["user_story_id"])
                best_score = best.final_score if best else 0.0

                def normalize_ac(ac_list):
                    return sorted([
                        ac.strip().lower()
                        for ac in (ac_list or [])
                        if ac and ac.strip()
                    ])

                is_same_content = (
                    best is not None
                    and (best.improved_story or "").strip() == new_story.strip()
                    and normalize_ac(best.generated_acceptance_criteria) == normalize_ac(new_ac)
                )

                # =========================
                # DECISION
                # =========================
                if best and new_score < best_score:
                    print("[SKIP] Worse than best")
                    version = best
                    has_new_version = False

                elif best and new_score == best_score and is_same_content:
                    print("[SKIP] Same as best")
                    version = best
                    has_new_version = False

                else:
                    print("[CREATE] New improved version")

                    version = await create_version(
                        db=db,
                        user_story_id=state["user_story_id"],
                        job_id=job_id,
                        improved_story=new_story,
                        acceptance_criteria=new_ac,
                        initial_score=initial_score,
                        final_score=new_score,
                        iteration=result.get("iteration", 0),
                        llm_calls=result.get("llm_calls"),
                        duration=duration,
                        model_used=result.get("model_used"),
                        prompt_tokens=result.get("prompt_tokens"),
                        completion_tokens=result.get("completion_tokens"),
                        testability_score=result.get("testability_score"),
                        is_testable=result.get("is_testable"),
                        testability_issues=result.get("testability_issues"),
                    )

                    has_new_version = True

                # =========================
                # COMPLETE
                # =========================
                job.status = JobStatus.COMPLETED
                job.phase = JobPhase.COMPLETED
                job.final_score = new_score
                job.iteration = result.get("iteration", 0)

                await db.commit()

                # =========================
                # FINAL SSE
                # =========================
                await push_event(job_id, "completed", {
                    "final_score": new_score,
                    "initial_score": initial_score,
                    "improved_story": new_story,
                    "acceptance_criteria": new_ac,
                    "iteration": result.get("iteration", 0),
                    "version_id": getattr(version, "id", None),
                    "has_new_version": has_new_version
                })

                print(f"[DONE] Pipeline finished")

            except asyncio.TimeoutError:
                # Possibilité de retry automatique
                job = await get_job_by_id(db, job_id)
                if job:
                    if job.retry_count < 3:  # Max 3 retries
                        job.retry_count += 1
                        job.status = JobStatus.PENDING
                        await db.commit()
                        
                        # Remettre dans la queue avec flag retry
                        state["is_retry"] = True
                        await job_queue.put(state)
                        print(f"[RETRY] Job {job_id} - attempt {job.retry_count}")
                    else:
                        job.status = JobStatus.FAILED
                        job.error = "Timeout after 3 retries"
                        await db.commit()
                        await push_event(job_id, "failed", {"error": "Pipeline timeout"})


            except Exception as e:
                traceback.print_exc()

                job = await get_job_by_id(db, job_id)
                if job:
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    await db.commit()

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