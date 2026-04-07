import time
from app.utils.common.pipeline_utils import safe_publish, add_trace
from app.services.jobs_service import store_job_result
from app.streaming.ui_events import publish_ui_phase
from app.services.frontend_state_service import FrontendStateService

async def rescore_node(state: dict) -> dict:
    if state.get("current_step") == "job_completed":    
        return state
    state.setdefault("events", [])
    start_time = time.time()

    jira_id = state.get("jira_id", "?")
    print(f"[{jira_id}] >>> [RESCORE]")

    current_score = state.get("final_score") or 0.0

    # Use initial_score as the true baseline
    previous_score = state.get("previous_score")
    if previous_score is None:
        previous_score = state.get("initial_score") or 0.0

    try:
        current_score = float(current_score)
        previous_score = float(previous_score)
    except Exception:
        current_score = previous_score = 0.0

    # If LLM failed, keep previous score
    if state.get("llm_failed"):
        print(f"[{jira_id}] [RESCORE] LLM failed → keep previous")
        current_score = previous_score

    delta = round(current_score - previous_score, 3)

    # Rollback if score degraded
    if delta < -0.01:
        print(f"[{jira_id}] [RESCORE] Degraded → rollback")
        state["improved_story"] = state.get("raw_story")
        current_score = previous_score
        delta = 0.0

    print(f"[{jira_id}] [RESCORE] prev={previous_score} current={current_score} delta={delta}")

    state["current_step"] = "rescoring"

    safe_publish(state, "rescoring", {
        "story_id": jira_id,
        "iteration": state.get("iteration", 0),
        "score_before": previous_score,
        "score_after": current_score,
        "delta": delta,
    })

    state.setdefault("events", []).append({
        "step": "rescoring"
    })
    state = add_trace(state, "rescore", {
        "previous_score": previous_score,
        "current_score": current_score,
        "delta": delta,
    })

    state.update({
        "final_score": current_score,
        "delta": delta,
        "best_score": max(state.get("best_score", 0.0), current_score),
        "score_after": current_score,
        "previous_score": current_score,
    })

    duration = round(time.time() - start_time, 3)
    state.setdefault("timing", {})
    state["timing"]["rescore"] = duration

    print(f"[{jira_id}] [RESCORE DONE] score={current_score} delta={delta} duration={duration}s")
    await FrontendStateService.update(state["job_id"], state)
    return state