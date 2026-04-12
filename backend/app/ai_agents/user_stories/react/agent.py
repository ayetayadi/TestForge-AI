"""
ReAct Agent for User Story processing.

Implements a Thought/Action/Observation cycle using the existing
LLM service (llm_service) as the reasoning engine. The agent
has access to analysis_tool, refinement_tool, and evaluate_tool
and decides the flow dynamically based on scores.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.llm.service import llm_service
from .tools import REACT_TOOLS_ASYNC

logger = logging.getLogger(__name__)

# ============================================================
# CONFIG
# ============================================================

SCORE_THRESHOLD = 0.8
MAX_ITERATIONS = 3
MAX_AGENT_STEPS = 10

# ============================================================
# REACT STEP PROMPT
# ============================================================

REACT_STEP_PROMPT = """You are a ReAct agent orchestrating a User Story quality improvement pipeline.

Available tools:
- analysis_tool: Analyzes story against INVEST criteria. Input: {{"action": "analysis_tool"}}
- refinement_tool: Refines story based on issues. Input: {{"action": "refinement_tool"}}
- evaluate_tool: Evaluates final quality after refinement. Input: {{"action": "evaluate_tool"}}
- finish: End the loop with a final decision. Input: {{"action": "finish", "decision": "approved"|"rejected", "score": <float>}}

DECISION RULES:
1. Always start with analysis_tool.
2. If score < {score_threshold} AND iterations < {max_iterations} → use refinement_tool.
3. After refinement_tool → always use evaluate_tool.
4. If evaluate_tool score >= {score_threshold} → finish with decision=approved.
5. If evaluate_tool score < {score_threshold} AND iterations >= {max_iterations} → finish with decision=rejected.
6. If story quality is already >= {score_threshold} at analysis → skip refinement, use evaluate_tool, then finish.

CURRENT CONTEXT:
Story: {raw_story}
Current Score: {current_score}
Iterations Done: {iterations}
Max Iterations: {max_iterations}

Previous steps:
{history}

What is the next action? Reply ONLY with valid JSON:
{{"thought": "<your reasoning>", "action": "<tool_name or finish>", "decision": "<approved|rejected if action=finish>", "score": <float if action=finish>}}
"""


# ============================================================
# REACT EXECUTOR
# ============================================================

class UserStoryReActExecutor:
    """
    Custom ReAct executor for User Story processing.

    Uses llm_service for reasoning and calls the appropriate
    async tool function based on the LLM decision.
    """

    def __init__(
        self,
        score_threshold: float = SCORE_THRESHOLD,
        max_iterations: int = MAX_ITERATIONS,
        max_steps: int = MAX_AGENT_STEPS,
    ):
        self.score_threshold = score_threshold
        self.max_iterations = max_iterations
        self.max_steps = max_steps

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the ReAct loop on the given state.

        Returns:
            Updated state with react_decision, reasoning, and final scores.
        """
        state = dict(state)
        state.setdefault("iterations", 0)
        state.setdefault("reasoning", [])
        state.setdefault("react_decision", "pending")

        jira_id = state.get("jira_id", "?")
        history: List[str] = []
        current_score = float(state.get("final_score") or state.get("initial_score") or 0.0)

        for step in range(self.max_steps):
            logger.info(f"[ReAct][{jira_id}] Step {step + 1} / {self.max_steps}")

            # --------------------------------------------------------
            # BUILD PROMPT
            # --------------------------------------------------------
            prompt = REACT_STEP_PROMPT.format(
                score_threshold=self.score_threshold,
                max_iterations=self.max_iterations,
                raw_story=state.get("raw_story", ""),
                current_score=current_score,
                iterations=state.get("iterations", 0),
                history="\n".join(history) if history else "None",
            )

            # --------------------------------------------------------
            # CALL LLM FOR REASONING
            # --------------------------------------------------------
            try:
                response = await llm_service.call(
                    prompt=prompt,
                    task="analysis",
                    use_cache=state.get("use_cache", True),
                )
                content = response.content if response.success else {}
                decision_raw = content if isinstance(content, dict) else {}
            except Exception as e:
                logger.error(f"[ReAct][{jira_id}] LLM reasoning failed: {e}")
                decision_raw = {}

            thought = decision_raw.get("thought", "No thought provided")
            action = decision_raw.get("action", "finish")

            log_entry = f"Step {step + 1} | Thought: {thought} | Action: {action}"
            history.append(log_entry)
            state["reasoning"].append(log_entry)

            logger.info(f"[ReAct][{jira_id}] {log_entry}")

            # --------------------------------------------------------
            # FINISH
            # --------------------------------------------------------
            if action == "finish":
                final_decision = decision_raw.get("decision", "rejected")
                final_score = float(decision_raw.get("score", current_score))
                state["react_decision"] = final_decision
                state["final_score"] = final_score
                observation = f"Finished with decision={final_decision}, score={final_score}"
                history.append(f"Observation: {observation}")
                state["reasoning"].append(f"Observation: {observation}")
                logger.info(f"[ReAct][{jira_id}] {observation}")
                break

            # --------------------------------------------------------
            # CALL TOOL
            # --------------------------------------------------------
            tool_fn = REACT_TOOLS_ASYNC.get(action)
            if tool_fn is None:
                observation = f"Unknown action '{action}' — finishing with current state"
                history.append(f"Observation: {observation}")
                state["reasoning"].append(f"Observation: {observation}")
                state["react_decision"] = "rejected"
                logger.warning(f"[ReAct][{jira_id}] {observation}")
                break

            try:
                tool_result = await tool_fn(state)
                observation = self._summarise_tool_result(action, tool_result)

                # Merge updated state from tool result
                inner_state = tool_result.get("state", {})
                if inner_state:
                    state.update(inner_state)

                # Track score
                if action in ("analysis_tool", "evaluate_tool"):
                    new_score = tool_result.get("final_score", current_score)
                    current_score = float(new_score)
                    state["final_score"] = current_score

                # Track iterations after refinement
                if action == "refinement_tool":
                    state["iterations"] = int(state.get("iterations", 0)) + 1
                    state["iteration"] = state["iterations"]

            except Exception as e:
                observation = f"Tool '{action}' raised an error: {e}"
                logger.error(f"[ReAct][{jira_id}] {observation}")
                state["react_decision"] = "rejected"

            history.append(f"Observation: {observation}")
            state["reasoning"].append(f"Observation: {observation}")
            logger.info(f"[ReAct][{jira_id}] Observation: {observation}")

            # --------------------------------------------------------
            # GUARD: auto-finish if max iterations hit
            # --------------------------------------------------------
            if (
                state.get("iterations", 0) >= self.max_iterations
                and action == "evaluate_tool"
            ):
                if current_score >= self.score_threshold:
                    state["react_decision"] = "approved"
                else:
                    state["react_decision"] = "rejected"
                logger.info(
                    f"[ReAct][{jira_id}] Auto-finish after max iterations: "
                    f"decision={state['react_decision']}"
                )
                break

        else:
            # Exceeded max_steps without a finish action
            if state.get("react_decision") in (None, "pending"):
                state["react_decision"] = "rejected"
            logger.warning(f"[ReAct][{jira_id}] Max steps reached")

        return state

    # --------------------------------------------------------
    # HELPERS
    # --------------------------------------------------------

    @staticmethod
    def _summarise_tool_result(action: str, result: Dict[str, Any]) -> str:
        """Build a concise Observation string from a tool result."""
        if action == "analysis_tool":
            score = result.get("final_score", 0.0)
            issues = result.get("llm_issues", [])
            return (
                f"analysis_tool → score={score:.3f}, "
                f"issues={len(issues)} ({', '.join(issues[:2]) if issues else 'none'})"
            )
        if action == "refinement_tool":
            status = result.get("refinement_status", "ok")
            improved = result.get("improved_story", "")[:80]
            ac_count = len(result.get("acceptance_criteria", []))
            return (
                f"refinement_tool → status={status}, "
                f"ac_count={ac_count}, story_preview='{improved}...'"
            )
        if action == "evaluate_tool":
            score = result.get("final_score", 0.0)
            decision = result.get("decision", "?")
            issues = result.get("llm_issues", [])
            return (
                f"evaluate_tool → score={score:.3f}, decision={decision}, "
                f"remaining_issues={len(issues)}"
            )
        return f"{action} → {json.dumps({k: v for k, v in result.items() if k != 'state'})}"


# ============================================================
# FACTORY
# ============================================================

def create_react_agent(
    score_threshold: float = SCORE_THRESHOLD,
    max_iterations: int = MAX_ITERATIONS,
    max_steps: int = MAX_AGENT_STEPS,
) -> UserStoryReActExecutor:
    """
    Create a configured UserStoryReActExecutor instance.

    Args:
        score_threshold: Minimum score to consider a story approved (default 0.8).
        max_iterations: Maximum number of refinement loops (default 3).
        max_steps: Maximum total agent steps before forced termination (default 10).

    Returns:
        Configured UserStoryReActExecutor.
    """
    return UserStoryReActExecutor(
        score_threshold=score_threshold,
        max_iterations=max_iterations,
        max_steps=max_steps,
    )
