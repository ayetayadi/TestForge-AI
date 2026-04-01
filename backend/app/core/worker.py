import asyncio
from app.core.job_queue import job_queue
from app.ai.agents.graph.graph import build_graph
from app.core.config import settings
from app.streaming.sse_manager import publish_event
from app.services.jobs_service import store_job_result

MAX_WORKERS = settings.MAX_WORKERS
graph = build_graph()


async def worker():
    while True:
        state = await job_queue.get()

        if state is None:
            break

        job_id = state.get("job_id")
        jira_id = state.get("jira_id")

        try:
            safe_state = state.copy()
            print(f"[WORKER] Processing {jira_id}")

            publish_event(job_id, "job_started", {
                "type": "job_started",
                "issue_key": jira_id,
            })

            result = await graph.ainvoke(safe_state, config={"recursion_limit": 15})

            await store_job_result(job_id, result)

            publish_event(job_id, "job_completed", {
                "type": "job_completed",
                "issue_key": jira_id,
                "score": result.get("final_score", 0),
                "initial_score": result.get("initial_score", 0),
                "iteration": result.get("iteration", 0),
            })

        except Exception as e:
            import traceback
            print(f"\n[WORKER ERROR] {jira_id}: {e}")
            traceback.print_exc()

            if job_id:
                publish_event(job_id, "job_failed", {
                    "type": "job_failed",
                    "issue_key": jira_id,
                    "error": str(e),
                })

        finally:
            job_queue.task_done()


async def start_workers():
    tasks = []

    for _ in range(MAX_WORKERS):
        task = asyncio.create_task(worker())
        tasks.append(task)

    print(f"[WORKERS] Started {MAX_WORKERS} workers")

    return tasks