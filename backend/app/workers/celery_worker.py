import copy
from typing import Dict, Any

from app.workers.celery_app import celery_app
from app.ai_agents.user_stories.pipeline.runner import run_user_story_pipeline
from app.ai_agents.user_stories.services.frontend_state_service import FrontendStateService
from app.ai_agents.user_stories.services.publishing_service import publishing_service


@celery_app.task(name="run_user_story_job")
def run_user_story_job(state: Dict[str, Any]):
    job_id = state.get("job_id")
    jira_id = state.get("jira_id")

    try:
        safe_state = copy.deepcopy(state)

        print(f"[CELERY] Processing {jira_id}")

        result = run_user_story_pipeline_sync(safe_state)

        FrontendStateService.sync_update(job_id, result)

        status = _compute_status(result)

        _publish_event(job_id, "completed", {
            "status": status,
            "score": result.get("final_score"),
        })

        return result

    except Exception as e:
        publishing_service.publish_phase(state, "failed")

        _publish_event(job_id, "failed", {
            "error": str(e),
        })

        raise


# =========================================================
# SYNC WRAPPER
# =========================================================
def run_user_story_pipeline_sync(state: Dict[str, Any]):
    import asyncio
    return asyncio.run(run_user_story_pipeline(state))


def _compute_status(result: Dict[str, Any]) -> str:
    if result.get("guard_failed"):
        return "failed"
    if result.get("final_score", 0) < 0.3:
        return "low_quality"
    return "completed"


def _publish_event(job_id: str, event: str, data: Dict[str, Any]):
    print(f"[EVENT] {event} | job={job_id} | {data}")