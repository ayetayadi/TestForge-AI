"""
Runner for the User Story ReAct Agent.

Entry point that mirrors run_user_story_pipeline() but uses the
ReAct multi-agent loop instead of the static LangGraph pipeline.
Compatible with the existing asyncio workers and checkpointing.
"""

import time
import copy
import logging
import traceback

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from app.utils.pipeline_utils import add_trace
from app.ai_agents.user_stories.utils.text_quality_utils import clean_raw_story
from app.ai_agents.user_stories.services.publishing_service import publishing_service
from app.ai_agents.user_stories.utils.testability_utils import compute_testability

from .agent import create_react_agent

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================
DEFAULT_SCORE_THRESHOLD = 0.8
DEFAULT_MAX_ITERATIONS = 3
DEFAULT_MAX_STEPS = 10
PIPELINE_TIMEOUT = 120  # seconds — enforced by asyncio_workers


# ============================================================
# MAIN RUNNER
# ============================================================

@traceable(name="user_story_react_pipeline")
async def run_user_story_react_agent(
    state: dict,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> dict:
    """
    Run the User Story ReAct Multi-Agent pipeline.

    This function is a drop-in replacement for run_user_story_pipeline().
    It wraps the analysis_node, refinement_node, and evaluate_node as tools
    and uses a ReAct executor to decide the flow dynamically via LLM reasoning.

    Args:
        state: Pipeline input dict. Required keys: job_id, jira_id, raw_story.
        score_threshold: Score >= threshold → story is approved (default 0.8).
        max_iterations: Max refinement loops (default 3).
        max_steps: Max total agent steps before forced termination (default 10).

    Returns:
        Updated state dict compatible with asyncio_workers expectations.
    """
    if not state:
        raise ValueError("state is None or empty")

    state = copy.deepcopy(state)

    jira_id = state.get("jira_id", "?")
    job_id = state.get("job_id")
    start_time = time.time()

    # ============================================================
    # VALIDATION
    # ============================================================
    if "job_id" not in state:
        raise ValueError("job_id is required")
    if "raw_story" not in state:
        raise ValueError("raw_story is required")

    # ============================================================
    # LANGSMITH METADATA
    # ============================================================
    run = get_current_run_tree()
    if run:
        run.metadata.update({
            "jira_id": jira_id,
            "job_id": job_id,
            "phase": "starting",
            "agent_type": "react",
        })

    # ============================================================
    # INITIALISATION
    # ============================================================
    state["status"] = "processing"
    state["raw_story"] = clean_raw_story(state["raw_story"])

    state.setdefault("initial_score", 0.0)
    state.setdefault("best_score", 0.0)
    state.setdefault("trace", [])
    state.setdefault("timing", {})
    state.setdefault("iteration", 0)
    state.setdefault("iterations", 0)
    state.setdefault("existing_ac", None)
    state.setdefault("consecutive_llm_failures", 0)
    state.setdefault("llm_calls", 0)
    state.setdefault("model_used", None)
    state.setdefault("prompt_tokens", 0)
    state.setdefault("completion_tokens", 0)
    state.setdefault("reasoning", [])
    state.setdefault("react_decision", "pending")

    state = add_trace(state, "react_start", {"story": state["raw_story"]})

    # ============================================================
    # CREATE AGENT
    # ============================================================
    agent = create_react_agent(
        score_threshold=score_threshold,
        max_iterations=max_iterations,
        max_steps=max_steps,
    )

    # ============================================================
    # PUBLISH PHASE
    # ============================================================
    try:
        await publishing_service.publish_phase(state, "analyzing")
    except Exception as e:
        logger.warning(f"[{jira_id}] publish_phase failed (non-fatal): {e}")

    # ============================================================
    # RUN REACT LOOP
    # ============================================================
    try:
        print(f"\n[{jira_id}] ===== REACT AGENT START =====")
        result = await agent.run(state)
        print(f"\n[{jira_id}] ===== REACT AGENT RESULT =====")
        print(f"[{jira_id}] decision={result.get('react_decision')} score={result.get('final_score')}")

    except Exception as e:
        traceback.print_exc()
        state["status"] = "failed"
        state["error"] = str(e)

        run = get_current_run_tree()
        if run:
            run.metadata.update({"status": "failed", "error": str(e)})

        await publishing_service.publish_failed(state)
        return state

    # ============================================================
    # POST-PROCESSING
    # ============================================================
    merged = state.copy()
    merged.update(result or {})
    result = merged

    if result.get("best_story"):
        result["improved_story"] = result["best_story"]
        result["acceptance_criteria"] = result.get("best_ac", [])

    duration = round(time.time() - start_time, 3)

    initial = float(result.get("initial_score") or 0.0)
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

    result = add_trace(result, "react_end", {
        "initial": initial,
        "final": final,
        "duration": duration,
        "react_decision": result.get("react_decision"),
        "iterations": result.get("iterations", 0),
    })

    # ============================================================
    # TESTABILITY
    # ============================================================
    story = result.get("improved_story") or result.get("raw_story")
    ac = result.get("acceptance_criteria", [])

    testability = compute_testability(story=story, acceptance_criteria=ac)
    result["testability_score"] = testability["score"]
    result["is_testable"] = testability["is_testable"]
    result["testability_issues"] = testability["issues"]

    # ============================================================
    # LANGSMITH METADATA FINALE
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
            "iterations": result.get("iterations", 0),
            "ac_count": len(result.get("acceptance_criteria", [])),
            "react_decision": result.get("react_decision"),
            "reasoning_steps": len(result.get("reasoning", [])),
            "agent_type": "react",
        })

    return result
