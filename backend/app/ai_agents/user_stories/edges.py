from app.ai_agents.user_stories.services.publishing_service import publishing_service
from app.ai_agents.user_stories.services.ac_service import ac_service
from app.ai_agents.user_stories.services.scoring_service import scoring_service

# =========================
# CONFIGURATION CONSTANTS
# =========================
MAX_ITER = 2
MAX_LLM_FAILURES = 2
MAX_LLM_CALLS = 5
MIN_VALID_AC = 3
SCORE_THRESHOLD = 0.95
MAX_TOKENS = 5000


# =========================================================
# ANALYSIS → REFINE / END
# =========================================================
def should_refine(state: dict) -> str:
    jira_id = state.get("jira_id", "?")

    score = float(state.get("final_score", 0.0))
    iteration = int(state.get("iteration", 0))
    llm_failures = state.get("consecutive_llm_failures", 0)
    llm_calls = state.get("llm_calls", 0)

    print(f"\n[{jira_id}] ===== REFINE CHECK =====")
    print(f"[{jira_id}] score={score} iteration={iteration} llm_calls={llm_calls}")

    # =========================================================
    # 1. LLM FAIL
    # =========================================================
    if llm_failures >= MAX_LLM_FAILURES:
        print(f"[{jira_id}] [STOP] Too many LLM failures")
        return "skip"

    # =========================================================
    # 2. LLM COST GUARD
    # =========================================================
    if llm_calls >= MAX_LLM_CALLS:
        print(f"[{jira_id}] [STOP] Too many LLM calls")
        return "skip"

    # =========================================================
    # 3. AC CHECK
    # =========================================================
    ac = ac_service.normalize(
        state.get("acceptance_criteria")
        or state.get("existing_ac")
        or []
    )

    valid_ac = ac_service.filter_testable(ac)

    if len(valid_ac) < MIN_VALID_AC:
        print(f"[{jira_id}] [FORCE REFINE] Weak AC")
        state["refine_ac_only"] = True
        return "refine"

    # =========================================================
    # 4. SCORE STOP
    # =========================================================
    if score >= SCORE_THRESHOLD:
        print(f"[{jira_id}] [STOP] Excellent quality")
        return "skip"

    # =========================================================
    # 5. ITER LIMIT
    # =========================================================
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

    llm_calls = state.get("llm_calls", 0)
    tokens = (state.get("prompt_tokens") or 0) + (state.get("completion_tokens") or 0)
    print(
        f"[{jira_id}] [RETRY_CHECK] "
        f"score={score:.3f} Δ={delta:.3f} iter={iteration} "
        f"llm_calls={llm_calls} tokens={tokens}"
    )

    # =========================================================
    # 1. LLM FAIL
    # =========================================================
    if llm_failures >= MAX_LLM_FAILURES:
        return "alert"

    # =========================================================
    # 2. TOKEN GUARD
    # =========================================================
    if tokens > MAX_TOKENS:
        print(f"[{jira_id}] [STOP] Token limit reached")
        return "end"

    # =========================================================
    # 3. GLOBAL STOP
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
    # 4. REFINEMENT SIGNAL
    # =========================================================
    if refinement_status == "rejected":
        print(f"[{jira_id}] [RETRY] Refinement rejected")

        if iteration >= MAX_ITER:
            return "end"

        return "retry"

    return "retry"