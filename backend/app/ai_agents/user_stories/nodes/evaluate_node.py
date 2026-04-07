import time
import copy
import asyncio
import logging
from typing import Dict, Any
from langsmith import get_current_run_tree, traceable

from app.utils.pipeline_utils import add_trace
from app.utils.llm_safety_utils import safe_float
from app.ai_agents.user_stories.utils.text_quality_utils import (
    detect_language,
    escape_braces,
)
from ..services.scoring_service import scoring_service
from ..services.publishing_service import publishing_service
from ..tools.constraint_guard import constraint_guard
from ..utils.text_sanitizer import sanitize_story
from ..utils.scoring_utils import compute_all_scores
from ..prompts.evaluate import EVALUATE_PROMPT

logger = logging.getLogger(__name__)


@traceable(name="evaluate_node")
async def evaluate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    state = copy.deepcopy(state)
    jira_id = state.get("jira_id", "?")
    iteration = state.get("iteration", 1)
    start_time = time.time()
    print(f"[EVALUATE_NODE] {jira_id} use_cache: {state.get('use_cache')}")

    state = add_trace(state, "evaluate_start", {"iteration": iteration})

    # ============================================================
    # UI (SSE CLEAN)
    # ============================================================
    await publishing_service.publish_phase(state, "evaluating")

    # ============================================================
    # INPUT
    # ============================================================
    story = state.get("improved_story") or state.get("raw_story") or ""
    story = sanitize_story(story)

    ac = state.get("acceptance_criteria") or []

    if not story:
        return state

    # ============================================================
    # CONSTRAINT GUARD
    # ============================================================
    guard_result = await _run_constraint_guard(
        original_story=state.get("raw_story"),
        improved_story=story,
        acceptance_criteria=ac,
    )

    guard_failed = guard_result["guard_failed"]
    state["guard_failed"] = guard_failed

    # ============================================================
    # ROLLBACK SI GUARD FAILED
    # ============================================================
    if guard_failed:
        best_story = state.get("best_story", state.get("raw_story"))
        best_ac = state.get("best_ac", state.get("existing_ac", []))

        story = best_story
        ac = best_ac

        state["improved_story"] = story
        state["acceptance_criteria"] = ac

    # ============================================================
    # PREVIOUS SCORE
    # ============================================================
    previous_score = safe_float(state.get("final_score", 0.0))

    # ============================================================
    # PROMPT
    # ============================================================
    language = state.get("language") or detect_language(story)

    prompt = EVALUATE_PROMPT.format(
        story=escape_braces(story),
        language=language,
        previous_score=previous_score,
        previous_issues="\n".join(state.get("llm_issues", [])[:5]) or "None"
    )

    print(f"\n[{jira_id}] ===== EVALUATE INPUT =====")
    print(f"[{jira_id}] STORY:\n{story}")
    print(f"[{jira_id}] AC ({len(ac)}): {ac}")
    print(f"[{jira_id}] PREVIOUS SCORE: {previous_score}")
    print(f"[{jira_id}] ===========================\n")

    # ============================================================
    # SCORING
    # ============================================================
    scores = await compute_all_scores(
        story=story,
        ac=ac,
        prompt=prompt,
        task="evaluation",
        fallback={
            "llm_score": 0.3,
            "llm_issues": [],
            "llm_suggestions": []
        },
        state=state
    )

    current_score = scores["final_score"]

    # ============================================================
    # PENALTY (SMART)
    # ============================================================
    if guard_failed:
        current_score = scoring_service.apply_guard_penalty(
            current_score,
            guard_failed
        )

    # ============================================================
    # IMPROVEMENT
    # ============================================================
    improvement = scoring_service.compute_improvement(
        previous_score,
        current_score
    )

    # ============================================================
    # BEST TRACKING
    # ============================================================
    if (
        not guard_failed and (
            current_score > state.get("best_score", 0)
            or len(ac) > len(state.get("best_ac", []))
        )
    ):
        state["best_score"] = current_score
        state["best_story"] = story
        state["best_ac"] = ac

    print(f"\n[{jira_id}] ===== EVALUATE OUTPUT =====")
    print(f"[{jira_id}] LLM SCORE: {scores['llm_score']}")
    print(f"[{jira_id}] FINAL SCORE: {current_score}")
    print(f"[{jira_id}] DELTA: {improvement['delta']}")
    print(f"[{jira_id}] ============================\n")

    # ============================================================
    # FINAL UPDATE
    # ============================================================
    duration = round(time.time() - start_time, 3)

    state.update({
        "rule_score": scores["rule_score"],
        "nlp_score": scores["nlp_score"],
        "llm_score": scores["llm_score"],
        "ac_score": scores["ac_score"],
        "final_score": current_score,
        "score_delta": improvement["delta"],

        "llm_issues": scores["llm_issues"],
        "llm_suggestions": scores["llm_suggestions"],
        "llm_failed": scores["llm_failed"],
    })

    state.setdefault("timing", {})
    state["timing"][f"evaluate_iter_{iteration}"] = duration

    run = get_current_run_tree()
    if run:
        run.metadata.update({
            "jira_id": jira_id,
            "iteration": iteration,
            "previous_score": previous_score,
            "current_score": current_score,
            "delta": improvement["delta"],
            "llm_score": scores["llm_score"],
            "llm_failed": scores["llm_failed"],
            "guard_failed": guard_failed,
            "duration": duration,
        })

    return state


# ============================================================
# GUARD
# ============================================================
async def _run_constraint_guard(
    original_story: str,
    improved_story: str,
    acceptance_criteria: list,
) -> Dict[str, Any]:

    try:
        result = await asyncio.to_thread(
            constraint_guard.validate,
            original=original_story,
            improved=improved_story,
            acceptance_criteria=acceptance_criteria
        )

        return {
            "guard_failed": not result.get("is_safe", True)
        }

    except Exception as e:
        print(f"[GUARD ERROR] {str(e)}")
        return {
            "guard_failed": False
        }