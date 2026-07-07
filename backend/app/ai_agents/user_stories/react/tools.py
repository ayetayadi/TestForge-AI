"""
ReAct Tools for User Story processing.

These @tool-decorated functions wrap the existing LangGraph nodes
(analysis_node, refinement_node, evaluate_node) so they can be
called by the ReAct agent as discrete actions.
"""

import asyncio
import logging
from typing import Dict, Any

from langchain_core.tools import tool

from app.ai_agents.user_stories.nodes.analysis_node import analysis_node
from app.ai_agents.user_stories.nodes.refinement_node import refinement_node
from app.ai_agents.user_stories.nodes.evaluate_node import evaluate_node

logger = logging.getLogger(__name__)


# ============================================================
# HELPERS
# ============================================================

def _run_async(coro):
    """
    Run an async coroutine from a sync context safely.

    NOTE: The sync @tool variants are provided for LangChain tool-registry
    compatibility (e.g. binding to a LangChain ChatModel). In practice the
    ReAct executor always calls the async variants in REACT_TOOLS_ASYNC directly,
    so these sync wrappers are only invoked when the @tool is used outside of
    the ReAct loop (e.g. in a LangChain agent executor).

    Spawning a new event loop via asyncio.run inside a thread pool worker avoids
    conflicts with the running event loop in the main asyncio worker, but means
    that async context variables (Redis connections, SQLAlchemy sessions) opened
    in the parent loop are NOT available inside the thread. The underlying nodes
    are stateless with respect to such resources, so this is safe here.
    """
    try:
        loop = asyncio.get_running_loop()
        # We are already inside an event loop — use a thread executor
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        return asyncio.run(coro)


# ============================================================
# ANALYSIS TOOL
# ============================================================

@tool
def analysis_tool(state: dict) -> Dict[str, Any]:
    """
    Analyzes a user story against INVEST criteria.

    Args:
        state: UserStoryReactState dict containing at minimum 'raw_story'.

    Returns:
        Dict with keys:
            - llm_score (float): INVEST quality score [0.0 – 1.0]
            - final_score (float): composite score
            - llm_issues (list): list of detected issues
            - llm_suggestions (list): list of improvement suggestions
            - invest_details (dict): per-criterion breakdown
    """
    try:
        result = _run_async(analysis_node(state))
        return {
            "llm_score": result.get("llm_score", 0.0),
            "final_score": result.get("final_score", 0.0),
            "llm_issues": result.get("llm_issues", []),
            "llm_suggestions": result.get("llm_suggestions", []),
            "invest_details": result.get("invest_details", {}),
            "state": result,
        }
    except Exception as e:
        logger.error(f"[analysis_tool] failed: {e}")
        return {
            "llm_score": 0.0,
            "final_score": 0.0,
            "llm_issues": [str(e)],
            "llm_suggestions": [],
            "invest_details": {},
            "state": state,
            "error": str(e),
        }


# ============================================================
# REFINEMENT TOOL
# ============================================================

@tool
def refinement_tool(state: dict) -> Dict[str, Any]:
    """
    Refines a user story based on previously identified issues.

    Args:
        state: UserStoryReactState dict. Must contain 'raw_story' and optionally
               'llm_issues', 'llm_suggestions', 'acceptance_criteria'.

    Returns:
        Dict with keys:
            - improved_story (str): the refined story text
            - acceptance_criteria (list): updated acceptance criteria
            - refinement_status (str): "ok" or "rejected"
            - state (dict): full updated state
    """
    try:
        result = _run_async(refinement_node(state))
        return {
            "improved_story": result.get("improved_story", state.get("raw_story", "")),
            "acceptance_criteria": result.get("acceptance_criteria", []),
            "refinement_status": result.get("refinement_status", "ok"),
            "state": result,
        }
    except Exception as e:
        logger.error(f"[refinement_tool] failed: {e}")
        return {
            "improved_story": state.get("improved_story", state.get("raw_story", "")),
            "acceptance_criteria": state.get("acceptance_criteria", []),
            "refinement_status": "rejected",
            "state": state,
            "error": str(e),
        }


# ============================================================
# EVALUATE TOOL
# ============================================================

@tool
def evaluate_tool(state: dict) -> Dict[str, Any]:
    """
    Evaluates the final quality of the (possibly refined) user story.

    Args:
        state: UserStoryReactState dict with 'improved_story' or 'raw_story'
               and 'acceptance_criteria'.

    Returns:
        Dict with keys:
            - final_score (float): composite quality score [0.0 – 1.0]
            - llm_score (float): LLM quality score
            - decision (str): "approved" if score >= 0.8 else "needs_refinement"
            - llm_issues (list): remaining issues
            - state (dict): full updated state
    """
    try:
        result = _run_async(evaluate_node(state))
        score = result.get("final_score", 0.0)
        decision = "approved" if score >= 0.8 else "needs_refinement"
        return {
            "final_score": score,
            "llm_score": result.get("llm_score", 0.0),
            "decision": decision,
            "llm_issues": result.get("llm_issues", []),
            "state": result,
        }
    except Exception as e:
        logger.error(f"[evaluate_tool] failed: {e}")
        return {
            "final_score": 0.0,
            "llm_score": 0.0,
            "decision": "needs_refinement",
            "llm_issues": [str(e)],
            "state": state,
            "error": str(e),
        }


# ============================================================
# ASYNC WRAPPERS
# ============================================================

async def analysis_tool_async(state: dict) -> Dict[str, Any]:
    """Async version of analysis_tool wrapping analysis_node directly."""
    try:
        result = await analysis_node(state)
        return {
            "llm_score": result.get("llm_score", 0.0),
            "final_score": result.get("final_score", 0.0),
            "llm_issues": result.get("llm_issues", []),
            "llm_suggestions": result.get("llm_suggestions", []),
            "invest_details": result.get("invest_details", {}),
            "state": result,
        }
    except Exception as e:
        logger.error(f"[analysis_tool_async] failed: {e}")
        return {
            "llm_score": 0.0,
            "final_score": 0.0,
            "llm_issues": [str(e)],
            "llm_suggestions": [],
            "invest_details": {},
            "state": state,
            "error": str(e),
        }


async def refinement_tool_async(state: dict) -> Dict[str, Any]:
    """Async version of refinement_tool wrapping refinement_node directly."""
    try:
        result = await refinement_node(state)
        return {
            "improved_story": result.get("improved_story", state.get("raw_story", "")),
            "acceptance_criteria": result.get("acceptance_criteria", []),
            "refinement_status": result.get("refinement_status", "ok"),
            "state": result,
        }
    except Exception as e:
        logger.error(f"[refinement_tool_async] failed: {e}")
        return {
            "improved_story": state.get("improved_story", state.get("raw_story", "")),
            "acceptance_criteria": state.get("acceptance_criteria", []),
            "refinement_status": "rejected",
            "state": state,
            "error": str(e),
        }


async def evaluate_tool_async(state: dict) -> Dict[str, Any]:
    """Async version of evaluate_tool wrapping evaluate_node directly."""
    try:
        result = await evaluate_node(state)
        score = result.get("final_score", 0.0)
        decision = "approved" if score >= 0.8 else "needs_refinement"
        return {
            "final_score": score,
            "llm_score": result.get("llm_score", 0.0),
            "decision": decision,
            "llm_issues": result.get("llm_issues", []),
            "state": result,
        }
    except Exception as e:
        logger.error(f"[evaluate_tool_async] failed: {e}")
        return {
            "final_score": 0.0,
            "llm_score": 0.0,
            "decision": "needs_refinement",
            "llm_issues": [str(e)],
            "state": state,
            "error": str(e),
        }


# ============================================================
# TOOL REGISTRY
# ============================================================

REACT_TOOLS = [analysis_tool, refinement_tool, evaluate_tool]

REACT_TOOLS_ASYNC = {
    "analysis_tool": analysis_tool_async,
    "refinement_tool": refinement_tool_async,
    "evaluate_tool": evaluate_tool_async,
}
