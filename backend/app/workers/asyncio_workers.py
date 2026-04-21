import asyncio
import traceback
import logging
from typing import Dict, Any, List
from datetime import datetime

from app.models.enums import AgentStatus, StoryDecision
from app.repositories.user_story_version_repository import get_best_version
from app.repositories.user_story_repository import get_user_story_by_id
from app.core.config import settings
from app.core.database import async_session_maker
from app.streaming.sse_manager import push_event
from app.ai_workflows.user_story_refinement.agent import get_pipeline
from app.models.user_story_version import UserStoryVersion
from .queue import job_queue

logger = logging.getLogger(__name__)

MAX_WORKERS = settings.MAX_WORKERS
AGENT_TIMEOUT = 120  # 2 minutes
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

    improved_story = result.get("improved_story", state["raw_story"])
    generated_ac = result.get("acceptance_criteria", state.get("acceptance_criteria", []))
    initial_score = float(result.get("initial_score", 0.0))
    final_score = float(result.get("final_score", 0.0))
    testability_score = float(result.get("testability_score", 0.0))
    is_testable = result.get("is_testable", False)
    testability_issues = result.get("testability_issues", [])
    iterations = result.get("iterations", 0)
    duration = result.get("duration_seconds", 0.0)
    agent_status_str = result.get("agent_status", "success")

    agent_status = (
        AgentStatus.FAILED
        if agent_status_str == "error"
        else AgentStatus.COMPLETED
    )

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
        agent_status=agent_status,
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

    logger.info(f"Version created: {version.id}, score={final_score:.3f}")
    return version


# ============================================================
# PROGRESS CALLBACK FACTORY
# ============================================================

def _make_progress_callback(version_id: str):
    async def cb(event_type: str, data: dict) -> None:
        await push_event(version_id, event_type, {**data, "timestamp": datetime.now().isoformat()})
    return cb


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
                        timeout=AGENT_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError(f"Agent timeout after {AGENT_TIMEOUT}s")

                # errors are returned as a result dict, not raised
                if result.get("agent_status") == "error":
                    logger.error(f"Agent reported error: {result.get('error')}")
                    failed_version = UserStoryVersion(
                        id=version_id,
                        user_story_id=state["user_story_id"],
                        improved_story=state["raw_story"],
                        generated_acceptance_criteria=state.get("acceptance_criteria", []),
                        agent_status=AgentStatus.FAILED,
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
                agent_status = result.get("agent_status", "unknown")
                duration = result.get("duration_seconds", 0.0)

                logger.info(
                    f"Agent result: initial={initial_score:.3f}, final={final_score:.3f}, "
                    f"delta={final_score - initial_score:+.3f}, "
                    f"testability={testability_score:.3f}, iterations={iterations}, "
                    f"status={agent_status}"
                )

                # ============================================================
                # VERSIONING LOGIC
                # ============================================================

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
                    "agent_status": agent_status,
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
                    #     "agent_status": agent_status,
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
                        agent_status=AgentStatus.FAILED,
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
                        agent_status=AgentStatus.FAILED,
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
