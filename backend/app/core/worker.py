import copy
import asyncio

from app.core.job_queue import job_queue
from app.ai.agents.graph.graph import build_graph
from app.core.config import settings
from app.streaming.sse_manager import publish_event
from app.streaming.ui_events import publish_ui_phase
from app.services.jobs_service import store_job_result
from app.services.frontend_state_service import FrontendStateService

MAX_WORKERS = settings.MAX_WORKERS
graph = build_graph()


async def c():
    while True:
        state = await job_queue.get()

        if state is None:
            break

        job_id = state.get("job_id")
        jira_id = state.get("jira_id")

        try:
            safe_state = copy.deepcopy(state)
            safe_state.setdefault("events", [])

            print(f"[WORKER] Processing {jira_id}")

            # ─── START EVENT ─────────────────────────────
            publish_event(job_id, "job_started", {
                "issue_key": jira_id,
            })

            # ─── EXECUTE GRAPH ───────────────────────────
            result = await graph.ainvoke(
                safe_state,
                config={"recursion_limit": 15}
            )

            # ─── FINAL STATE ─────────────────────────────
            result["current_step"] = "job_completed"

            await FrontendStateService.update(job_id, result)
            await store_job_result(job_id, result)

            # ─── UI PHASE FINAL ──────────────────────────
            publish_ui_phase(result, "completed")

            # ─── COMPUTE STATUS ──────────────────────────
            status = "failed" if result.get("llm_failed") else "completed"

            # ─── SINGLE CLEAN EVENT ──────────────────────
            publish_event(job_id, "job_completed", {
                "status": status,
                "score_before": result.get("initial_score", 0),
                "score_after": result.get("final_score", 0),
                "delta": result.get("delta", 0),
                "iteration": result.get("iteration", 0),
                "outcome": result.get("outcome", "approved"),
                "improved_story": result.get("improved_story", ""),
                "acceptance_criteria": result.get("acceptance_criteria", []),
            })

            safe_state["events"].append({
                "step": "job_completed"
            })

        except Exception as e:
            import traceback
            print(f"\n[WORKER ERROR] {jira_id}: {e}")
            traceback.print_exc()

            if job_id:
                publish_ui_phase(state, "failed")

                publish_event(job_id, "job_failed", {
                    "issue_key": jira_id,
                    "error": str(e),
                })

        finally:
            job_queue.task_done()


workers = []


async def start_workers():
    for _ in range(MAX_WORKERS):
        task = asyncio.create_task(async_worker())
        workers.append(task)

    print(f"[WORKERS] Started {MAX_WORKERS} workers")


async def stop_workers():
    for _ in range(len(workers)):
        await job_queue.put(None)

    await asyncio.gather(*workers, return_exceptions=True)

    print("[WORKERS] All workers stopped")