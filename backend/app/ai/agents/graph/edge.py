from langgraph.graph import END
from app.utils.common.text_quality_utils import is_testable_ac
from app.utils.common.ac_utils import (
    detect_story_type,
    get_ac_threshold,
    compute_ac_score,
)
from app.utils.common.pipeline_utils import safe_publish
from app.services.jobs_service import store_job_result

MAX_ITER = 2


# =========================
# REFINE DECISION
# =========================
def should_refine(state: dict) -> str:
    jira_id = state.get("jira_id", "?")
    iteration = state.get("iteration", 0)
    delta = float(state.get("delta", 0.0) or 0.0)
    final_score = float(state.get("final_score", 0.0) or 0.0)

    # reset flag propre
    state["refine_ac_only"] = False

    # safe AC
    ac = state.get("acceptance_criteria") or state.get("existing_ac") or []
    valid_ac = [a for a in ac if is_testable_ac(a)]
    ac_len = len(ac)
    ratio = len(valid_ac) / max(ac_len, 1)

    # 🔴 LLM FAIL → seulement skip si répété
    if state.get("llm_failed") and state.get("consecutive_llm_failures", 0) >= 2:
        print(f"[{jira_id}] [SKIP] Repeated LLM failure")
        return "skip_to_human"

    # ✔ stabilité delta
    if iteration > 0 and abs(delta) <= 0.01 and final_score >= 0.85:
        print(f"[{jira_id}] [SKIP] No improvement + good quality")
        return "skip_to_human"

    # critical issues
    if state.get("critical_issues"):
        print(f"[{jira_id}] [REFINE] Critical issues")
        return "refine"

    # excellent
    if final_score >= 0.95 and len(valid_ac) >= 2:
        print(f"[{jira_id}] [SKIP] Excellent quality")
        return "skip_to_human"

    # high score
    if final_score >= 0.9:
        if ratio >= 0.7 and len(valid_ac) >= 2:
            print(f"[{jira_id}] [SKIP] High quality story + AC")
            return "skip_to_human"

        print(f"[{jira_id}] [REFINE] High score but weak AC (ratio={ratio:.2f})")
        state["refine_ac_only"] = True
        return "refine"

    # AC evaluation
    story = (
        state.get("improved_story")
        if state.get("is_reanalysis")
        else state.get("raw_story", "")
    )

    story_type = detect_story_type(story)
    ac_score = compute_ac_score(ac, is_testable_ac)
    threshold = get_ac_threshold(story_type)

    print(f"[{jira_id}] [AC CHECK] type={story_type} score={ac_score} threshold={threshold}")

    if ac_score < threshold:
        print(f"[{jira_id}] [REFINE] AC too low")
        return "refine"

    print(f"[{jira_id}] [SKIP] Acceptable quality")
    return "skip_to_human"

# =========================
# RETRY DECISION
# =========================
def should_retry(state: dict) -> str:
    if state.get("current_step") == "job_completed":    
        return state
    jira_id = state.get("jira_id", "?")

    score = float(state.get("final_score", 0.0) or 0.0)
    delta = float(state.get("delta", 0.0) or 0.0)
    iteration = state.get("iteration", 0)
    llm_failures = state.get("consecutive_llm_failures", 0)

    print(f"[{jira_id}] [RETRY CHECK] score={score} delta={delta} iter={iteration} llm_fail={llm_failures}")

    def complete_job():
        state["current_step"] = "job_completed"

        safe_publish(state, "job_completed", {
            "story_id": jira_id,
            "score": score,
            "iteration": iteration
        })

        state.setdefault("events", []).append({
            "step": "job_completed"
        })

    if llm_failures >= 2:
        print(f"[{jira_id}] [STOP] Too many LLM failures")
        complete_job()
        return "alert"

    if score >= 0.9:
        ac = state.get("acceptance_criteria") or []
        valid = [a for a in ac if is_testable_ac(a)]

        if len(valid) < 2 and iteration < MAX_ITER:
            print(f"[{jira_id}] [RETRY] High score but weak AC")
            state["refine_ac_only"] = True
            return "retry"

        print(f"[{jira_id}] [STOP] High quality reached")
        complete_job()
        return "end"

    if iteration > 0 and abs(delta) <= 0.01:
        if score < 0.8 and iteration < MAX_ITER:
            print(f"[{jira_id}] [RETRY] Low score + no improvement → retry")
            return "retry"

        print(f"[{jira_id}] [STOP] No meaningful improvement")
        complete_job()
        return "end"

    if iteration >= MAX_ITER:
        print(f"[{jira_id}] [STOP] Max iterations reached")
        complete_job()
        return "end"

    print(f"[{jira_id}] [RETRY] Continue refinement")
    return "retry"