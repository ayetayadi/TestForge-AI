from app.ai_agents.user_stories.services.publishing_service import publishing_service
from app.ai_agents.user_stories.services.ac_service import ac_service
from app.ai_agents.user_stories.services.scoring_service import scoring_service

MAX_ITER = 2


# =========================================================
# ANALYSIS → REFINE / END
# =========================================================
def should_refine(state: dict) -> str:
    jira_id = state.get("jira_id", "?")

    score = float(state.get("final_score", 0.0))
    iteration = int(state.get("iteration", 0))
    llm_failures = state.get("consecutive_llm_failures", 0)

    print(f"\n[{jira_id}] ===== REFINE CHECK =====")
    print(f"[{jira_id}] score={score} iteration={iteration}")

    # LLM FAIL
    if llm_failures >= 2:
        print(f"[{jira_id}] [STOP] Too many LLM failures")
        return "skip"

    # AC CHECK
    ac = ac_service.normalize(
        state.get("acceptance_criteria")
        or state.get("existing_ac")
        or []
    )

    valid_ac = ac_service.filter_testable(ac)

    if len(valid_ac) < 2:
        print(f"[{jira_id}] [FORCE REFINE] Weak AC")
        state["refine_ac_only"] = True
        return "refine"

    # SCORE STOP
    if score >= 0.95:
        print(f"[{jira_id}] [STOP] Excellent quality")
        return "skip"

    # ITER LIMIT
    if iteration >= MAX_ITER:
        print(f"[{jira_id}] [STOP] Max iterations reached")
        return "skip"

    return "refine"


# =========================================================
# EVALUATE → RETRY / END
# =========================================================
def should_retry(state: dict):
    jira_id = state.get("jira_id", "?")

    score = float(state.get("final_score", 0.0))
    delta = float(state.get("score_delta", 0.0))
    iteration = int(state.get("iteration", 0))
    llm_failures = state.get("consecutive_llm_failures", 0)
    refinement_status = state.get("refinement_status", "ok")

    print(f"[{jira_id}] [RETRY_CHECK] score={score:.3f} Δ={delta:.3f} iter={iteration}")

    # =========================================================
    # 1. LLM FAIL
    # =========================================================
    if llm_failures >= 2:
        return "alert"

    # =========================================================
    # 2. GLOBAL STOP
    # =========================================================
    stop, reason = scoring_service.should_stop(
        score=score,
        iteration=iteration,
        delta=delta,
        max_iterations=MAX_ITER
    )

    if stop:
        print(f"[{jira_id}] [STOP] {reason}")

        state["improved_story"] = state.get("best_story")
        state["acceptance_criteria"] = state.get("best_ac")

        return "end"

    # =========================================================
    # 3. REFINEMENT SIGNAL
    # =========================================================
    if refinement_status == "rejected":
        print(f"[{jira_id}] [RETRY] Refinement rejected")

        if iteration >= MAX_ITER:
            return "end"

        return "retry"

    # =========================================================
    # 4. CONTINUE
    # =========================================================
    return "retry"