import time
import copy
import traceback
from app.ai.agents.graph.graph import build_graph
from app.utils.common.pipeline_utils import add_trace
from app.utils.common.text_quality_utils import clean_raw_story


def run_user_story_pipeline(state: dict) -> dict:
    state = copy.deepcopy(state)

    graph_pipeline = build_graph()

    jira_id = state.get("jira_id")
    print(f"\n[PIPELINE START] {jira_id}")
    start_time = time.time()

    if "job_id" not in state:
        raise ValueError("job_id is required")
    if "raw_story" not in state:
        raise ValueError("raw_story is required")

    state["raw_story"] = clean_raw_story(state["raw_story"])

    state.setdefault("initial_score", None)
    state.setdefault("best_score", 0.0)
    state.setdefault("trace", [])
    state.setdefault("timing", {})
    state.setdefault("iteration", 0)
    state.setdefault("existing_ac", None)
    state.setdefault("is_reanalysis", False)
    state.setdefault("skip_reanalysis", False)

    state = add_trace(state, "start", {"story": state["raw_story"]})

    try:
        result = graph_pipeline.invoke(state, config={"recursion_limit": 15})

    except Exception as e:
        print(f"[PIPELINE ERROR] {jira_id}: {type(e).__name__}: {e}")
        traceback.print_exc()
        return state

    result = add_trace(result, "end", {
        "final_score": result.get("final_score"),
        "initial_score": result.get("initial_score"),
        "delta": result.get("delta"),
    })

    duration = round(time.time() - start_time, 3)
    initial = result.get("initial_score") or 0.0
    final = result.get("final_score") or 0.0
    improvement = round(final - initial, 2)

    result.update({
        "initial_score": initial,
        "final_score": final,
        "score_improvement": improvement,
        "score_summary": {
            "initial": initial,
            "final": final,
            "improvement": improvement,
            "improved": final > initial,
        },
    })

    print(f"[PIPELINE END] {jira_id} ({duration}s) initial={initial} final={final} improvement={improvement}")

    return result