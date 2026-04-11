import time
import copy
import traceback

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from app.ai_agents.user_stories.graph import build_graph
from app.utils.pipeline_utils import add_trace
from app.ai_agents.user_stories.utils.text_quality_utils import clean_raw_story
from app.ai_agents.user_stories.services.publishing_service import publishing_service
from app.ai_agents.user_stories.utils.testability_utils import compute_testability

graph_pipeline = build_graph()


@traceable(name="user_story_pipeline")
async def run_user_story_pipeline(state: dict) -> dict:
    if not state:
        raise ValueError("state is None or empty")
    
    print(f"[RUNNER] BEFORE deepcopy - use_cache: {state.get('use_cache')}")
    state = copy.deepcopy(state)
    print(f"[RUNNER] AFTER deepcopy - use_cache: {state.get('use_cache')}")

    jira_id = state.get("jira_id", "?")
    start_time = time.time()

    print(f"[RUNNER] {jira_id} use_cache: {state.get('use_cache')}")

    # ============================================================
    # LANGSMITH — METADATA INITIALE
    # ============================================================
    run = get_current_run_tree()
    if run:
        run.metadata.update({
            "jira_id": jira_id,
            "job_id": state.get("job_id"),
            "phase": "starting",
        })

    if "job_id" not in state:
        raise ValueError("job_id is required")

    if "raw_story" not in state:
        raise ValueError("raw_story is required")

    state["status"] = "processing"
    state["raw_story"] = clean_raw_story(state["raw_story"])

    state.setdefault("initial_score", 0.0)
    state.setdefault("best_score", 0.0)
    state.setdefault("trace", [])
    state.setdefault("timing", {})
    state.setdefault("iteration", 0)
    state.setdefault("existing_ac", None)
    state.setdefault("consecutive_llm_failures", 0)
    state.setdefault("llm_calls", 0)
    state.setdefault("model_used", None)
    state.setdefault("prompt_tokens", 0)
    state.setdefault("completion_tokens", 0)

    state = add_trace(state, "start", {
        "story": state["raw_story"]
    })

    try:
        print(f"\n[{jira_id}] ===== PIPELINE START =====")

        result = await graph_pipeline.ainvoke(
            state,
            config={"recursion_limit": 15}
        )

        print(f"\n[{jira_id}] ===== PIPELINE RESULT =====")
        print(result)

    except Exception as e:
        traceback.print_exc()
        state["status"] = "failed"
        state["error"] = str(e)

        # ============================================================
        # LANGSMITH — LOG ERREUR
        # ============================================================
        run = get_current_run_tree()
        if run:
            run.metadata.update({
                "status": "failed",
                "error": str(e),
            })

        await publishing_service.publish_failed(state)
        return state

    if result and "__end__" in result:
        result = result["__end__"]

    merged = state.copy()
    merged.update(result or {})
    result = merged

    if result.get("best_story"):
        result["improved_story"] = result["best_story"]
        result["acceptance_criteria"] = result.get("best_ac", [])


    duration = round(time.time() - start_time, 3)

    initial = float(result.get("initial_score") or result.get("final_score") or 0.0)
    final = float(result.get("final_score") or 0.0)

    result.update({
        "initial_score": initial,
        "final_score": final,
        "duration": duration,
        "status": "completed",
        "llm_calls": result.get("llm_calls", 0),
        "model_used": result.get("model_used"),
        "prompt_tokens": result.get("prompt_tokens"),
        "completion_tokens": result.get("completion_tokens"),
    })

    result = add_trace(result, "end", {
        "initial": initial,
        "final": final,
        "duration": duration
    })

    # =========================
    # TESTABILITY COMPUTATION
    # =========================
    story = result.get("raw_story")
    ac = result.get("acceptance_criteria", [])
    
    testability = compute_testability(
        story=story,
        acceptance_criteria=ac
    )
    
    result["testability_score"] = testability["score"]
    result["is_testable"] = testability["is_testable"]
    result["testability_issues"] = testability["issues"]

    # ============================================================
    # LANGSMITH — METADATA FINALE
    # ============================================================
    run = get_current_run_tree()
    if run:
        run.metadata.update({
            "jira_id": jira_id,
            "status": "completed",
            "initial_score": initial,
            "final_score": final,
            "score_delta": round(final - initial, 3),
            "duration": duration,
            "iterations": result.get("iteration", 0),
            "ac_count": len(result.get("acceptance_criteria", [])),
            "llm_failed": result.get("llm_failed", False),
        })

    return result