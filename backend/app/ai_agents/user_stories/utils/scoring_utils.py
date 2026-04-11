import asyncio
import json
from typing import Dict, Any

from app.utils.pipeline_utils import add_trace
from app.utils.llm_safety_utils import safe_float

from app.llm.service import llm_service
from ..services.scoring_service import ScoreComponents
from ..services.ac_service import ac_service
from ..tools.rules_engine import rule_engine
from ..tools.nlp_checker import nlp_checker
from ..tools.garbage_detector import garbage_detector


async def compute_all_scores(
    story: str,
    ac: list,
    prompt: str,
    task: str,
    fallback: Dict[str, Any],
    state: Dict[str, Any]
) -> Dict[str, Any]:

    jira_id = state.get("jira_id", "?")
    iteration = state.get("iteration", 0)

    # ============================================================
    # SAFE INIT
    # ============================================================
    state["prompt_tokens"] = state.get("prompt_tokens", 0)
    state["completion_tokens"] = state.get("completion_tokens", 0)
    state["llm_calls"] = state.get("llm_calls", 0)

    ac = ac or []

    # ============================================================
    # TRACE INPUT
    # ============================================================
    state = add_trace(state, "scoring_start", {
        "jira_id": jira_id,
        "iteration": iteration
    })

    # ============================================================
    # PARALLEL EXECUTION
    # ============================================================
    rule_task = asyncio.to_thread(rule_engine.evaluate, story)
    nlp_task = asyncio.to_thread(nlp_checker.analyze, story)
    llm_task = llm_service.call_with_fallback(
        prompt=prompt,
        task=task,
        fallback=fallback,
        use_cache=state.get("use_cache", True),
    )

    results = await asyncio.gather(
        rule_task,
        nlp_task,
        llm_task,
        return_exceptions=True
    )

    rule_result, nlp_result, llm_response = results

    # ============================================================
    # LLM RESPONSE
    # ============================================================
    if isinstance(llm_response, Exception):
        print("LLM ERROR:", llm_response)
        llm_response = {}

    if isinstance(llm_response, str):
        try:
            llm_response = json.loads(llm_response)
        except Exception as e:
            print("JSON PARSE ERROR:", e)
            llm_response = {}

    # ============================================================
    # LLM METRICS
    # ============================================================
    if not isinstance(llm_response, Exception):
        state["llm_calls"] += 1

        if isinstance(llm_response, dict):
            state["prompt_tokens"] += llm_response.get("prompt_tokens", 0)
            state["completion_tokens"] += llm_response.get("completion_tokens", 0)
            state["model_used"] = llm_response.get("model")

        elif getattr(llm_response, "content", None):
            state["prompt_tokens"] += getattr(llm_response, "prompt_tokens", 0) or 0
            state["completion_tokens"] += getattr(llm_response, "completion_tokens", 0) or 0
            state["model_used"] = getattr(llm_response, "model", None)

    # ============================================================
    # TRACE RAW RESULTS
    # ============================================================
    state = add_trace(state, "scoring_raw_results", {
        "iteration": iteration,
        "rule_result": str(rule_result),
        "nlp_result": str(nlp_result),
        "llm_response": str(llm_response)
    })

    # ============================================================
    # RULE SCORE
    # ============================================================
    if isinstance(rule_result, Exception):
        print("RULE ERROR:", rule_result)
        rule_score = 0.0
    else:
        rule_score = _extract_score(
            result=rule_result,
            key="rule_score",
            source="rule_engine",
            jira_id=jira_id,
            state=state
        )

    # ============================================================
    # NLP SCORE
    # ============================================================
    if isinstance(nlp_result, Exception):
        print("NLP ERROR:", nlp_result)
        nlp_score = 0.0
    else:
        nlp_score = _extract_score(
            result=nlp_result,
            key="nlp_score",
            source="nlp_checker",
            jira_id=jira_id,
            state=state
        )

    # ============================================================
    # LLM SCORE
    # ============================================================
    if isinstance(llm_response, dict):
        llm_score = safe_float(llm_response.get("llm_score", 0.3))
        llm_issues = llm_response.get("llm_issues", [])
        llm_suggestions = llm_response.get("llm_suggestions", [])
        llm_failed = False
    else:
        llm_score = fallback.get("llm_score", 0.3)
        llm_issues = fallback.get("llm_issues", [])
        llm_suggestions = fallback.get("llm_suggestions", [])
        llm_failed = True

    # ============================================================
    # FINAL SCORE
    # ============================================================
    ac_score = ac_service.compute_score(ac)
    is_garbage = garbage_detector.is_garbage(story)

    components = ScoreComponents(
        llm_score=llm_score,
        ac_score=ac_score,
        rule_score=rule_score,
        nlp_score=nlp_score,
        is_garbage=is_garbage
    )

    final_score = components.normalized

    # ============================================================
    # TRACE OUTPUT
    # ============================================================
    state = add_trace(state, "scoring_output", {
        "iteration": iteration,
        "scores": {
            "llm": llm_score,
            "rule": rule_score,
            "nlp": nlp_score,
            "ac": ac_score,
            "final": round(final_score, 3)
        }
    })

    return {
        "rule_score": rule_score,
        "nlp_score": nlp_score,
        "llm_score": llm_score,
        "ac_score": ac_score,
        "llm_issues": llm_issues,
        "llm_suggestions": llm_suggestions,
        "llm_failed": llm_failed,
        "is_garbage": is_garbage,
        "final_score": round(final_score, 3),
    }


# ============================================================
# SAFE EXTRACT SCORE
# ============================================================
def _extract_score(result, key, source, jira_id, state):

    if isinstance(result, Exception):
        print(f"{source.upper()} ERROR:", result)
        return 0.0

    if isinstance(result, dict):
        return safe_float(result.get(key, 0))

    return 0.0