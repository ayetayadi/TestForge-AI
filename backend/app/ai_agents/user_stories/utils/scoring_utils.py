import asyncio
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
    # RAW DEBUG (IMPORTANT)
    # ============================================================
    state = add_trace(state, "scoring_raw_results", {
        "iteration": iteration,
        "rule_result": str(rule_result),
        "nlp_result": str(nlp_result),
        "llm_response": str(llm_response)
    })

    # ============================================================
    # EXTRACT RULE SCORE
    # ============================================================
    rule_score = _extract_score(
        result=rule_result,
        key="rule_score",
        source="rule_engine",
        jira_id=jira_id,
        state=state
    )

    # ============================================================
    # EXTRACT NLP SCORE
    # ============================================================
    nlp_score = _extract_score(
        result=nlp_result,
        key="nlp_score",
        source="nlp_checker",
        jira_id=jira_id,
        state=state
    )

    # ============================================================
    # EXTRACT LLM RESULT
    # ============================================================
    if isinstance(llm_response, Exception):
        llm_score = fallback.get("llm_score", 0.3)
        llm_issues = fallback.get("llm_issues", [])
        llm_suggestions = fallback.get("llm_suggestions", [])
        llm_failed = True

        state = add_trace(state, "llm_error", {
            "iteration": iteration,
            "error": str(llm_response)
        })

    elif isinstance(llm_response, dict):
        llm_score = safe_float(llm_response.get("llm_score", 0.3))
        llm_issues = llm_response.get("llm_issues", [])
        llm_suggestions = llm_response.get("llm_suggestions", [])
        llm_failed = False 

    elif getattr(llm_response, "success", False) and getattr(llm_response, "content", None):
        content = llm_response.content

        llm_score = safe_float(content.get("llm_score", 0.3))
        llm_issues = content.get("llm_issues", [])
        llm_suggestions = content.get("llm_suggestions", [])
        llm_failed = False

    else:
        llm_score = fallback.get("llm_score", 0.3)
        llm_issues = fallback.get("llm_issues", [])
        llm_suggestions = fallback.get("llm_suggestions", [])
        llm_failed = True

        state = add_trace(state, "llm_fallback_used", {
            "iteration": iteration
        })

    # ============================================================
    # COMPUTE FINAL SCORE
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
    # TRACE INPUT / OUTPUT
    # ============================================================
    state = add_trace(state, "scoring_input", {
        "iteration": iteration,
        "story": story,
        "ac": ac
    })

    state = add_trace(state, "scoring_output", {
        "iteration": iteration,
        "scores": {
            "llm": llm_score,
            "rule": rule_score,
            "nlp": nlp_score,
            "ac": ac_score,
            "final": round(final_score, 3)
        },
        "flags": {
            "llm_failed": llm_failed,
            "is_garbage": is_garbage
        },
        "llm_feedback": {
            "issues": llm_issues,
            "suggestions": llm_suggestions
        }
    })

    # ============================================================
    # RETURN
    # ============================================================
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


def _extract_score(
    result: Any,
    key: str,
    source: str,
    jira_id: str,
    state: Dict[str, Any]
) -> float:

    if isinstance(result, Exception):
        state = add_trace(state, f"{source}_error", {
            "jira_id": jira_id,
            "error": str(result)
        })
        return 0.0

    if isinstance(result, dict):
        return safe_float(result.get(key, 0))

    return 0.0