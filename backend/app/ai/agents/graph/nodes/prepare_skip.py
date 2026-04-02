import time
from app.utils.common.pipeline_utils import safe_publish
from app.utils.common.text_quality_utils import is_testable_ac
from app.services.jobs_service import store_job_result

async def prepare_skip_node(state: dict) -> dict:
    state.setdefault("events", [])
    start_time = time.time()

    jira_id = state.get("jira_id", "?")
    print(f"[{jira_id}] [PREPARE SKIP]")

    raw_story = state.get("raw_story")
    existing_ac = state.get("existing_ac") or []
    score = state.get("final_score") or 0.0

    existing_ac_valid = [a for a in existing_ac if is_testable_ac(a)]

    ac_ok = len(existing_ac_valid) >= 2 and (len(existing_ac_valid) / max(len(existing_ac), 1)) >= 0.6

    if not ac_ok:
        print(f"[{jira_id}] [PREPARE SKIP] AC insufficient → refinement")
        state["skip_reanalysis"] = False

        state["current_step"] = "prepare_skip_failed"

        state.setdefault("timing", {})
        state["timing"]["prepare_skip"] = round(time.time() - start_time, 3)

        await store_job_result(state["job_id"], state)
        return state

    print(f"[{jira_id}] [PREPARE SKIP] AC OK → end pipeline")

    state["current_step"] = "prepare_skip_done"

    safe_publish(state, "skipped", {
        "story_id": jira_id,
        "score": score,
    })

    state.update({
        "improved_story": raw_story,
        "acceptance_criteria": existing_ac,
        "score_after": score,
        "final_score": score,
        "previous_score": score,
        "best_score": max(state.get("best_score", 0.0), score),
        "delta": 0.0,
        "skip_reanalysis": True,
    })

    state.setdefault("events", []).append({
        "step": "prepare_skip_done"
    })

    state.setdefault("timing", {})
    state["timing"]["prepare_skip"] = round(time.time() - start_time, 3)

    await store_job_result(state["job_id"], state)

    return state