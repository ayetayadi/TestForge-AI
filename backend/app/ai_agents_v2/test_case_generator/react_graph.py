"""Generic ReAct graph builder."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, FrozenSet

from langgraph.graph import END, StateGraph

logger = logging.getLogger(__name__)

MAX_REFINEMENT_ROUNDS = 2


def build_react_graph(
    state_class:    type,
    agent_node:     Callable,
    tool_node:      Callable,
    terminal_tools: FrozenSet[str],
):
    graph = StateGraph(state_class)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")

    # ── Auto-save node ─────────────────────────────────────────────────────────
    # Skips the LLM entirely: test cases are already in state from draft/refine.
    # Saves one full API round-trip (the LLM would only re-echo what it already said).
    def _auto_save_node(state: dict) -> Dict[str, Any]:
        logger.info("[react_graph] Auto-saving — quality OK, no extra LLM call needed.")
        return {
            "approved": True,
            "user_story_analysis": state.get("user_story_analysis") or {"scope": "", "goals": []},
        }

    graph.add_node("auto_save", _auto_save_node)

    def _route_after_agent(state: dict) -> str:
        messages = state.get("messages") or []
        if not messages:
            return "end"
        last = messages[-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return "end"

    def _route_after_tools(state: dict) -> str:
        # Already finished via terminal flag
        if state.get("approved") or state.get("flagged_for_human"):
            return "end"

        messages = state.get("messages") or []

        # Finished via terminal tool call (save_test_cases / flag_human_review)
        for msg in reversed(messages):
            tool_calls = getattr(msg, "tool_calls", None) or []
            if tool_calls:
                for tc in tool_calls:
                    if tc.get("name") in terminal_tools:
                        return "end"
                break

        # Auto-save when the auto-critique says quality is good — no LLM needed.
        # The test cases are already in state["test_cases_structured"] from the
        # draft or refine tool call, so we just set approved=True and stop.
        critique = state.get("critique_result") or {}
        if critique.get("quality_ok") and state.get("test_cases_structured"):
            logger.info("[react_graph] quality_ok=True → auto_save (skipping LLM save call).")
            return "auto_save"

        # Max refinement rounds reached — save the best we have, skip LLM.
        refine_rounds = sum(
            1
            for msg in messages
            for tc in (getattr(msg, "tool_calls", None) or [])
            if tc.get("name") == "refine_test_cases"
        )
        if refine_rounds >= MAX_REFINEMENT_ROUNDS:
            if state.get("test_cases_structured"):
                logger.warning(
                    "[react_graph] Max refinement rounds (%d) reached → auto_save.",
                    MAX_REFINEMENT_ROUNDS,
                )
                return "auto_save"

        return "agent"

    graph.add_conditional_edges(
        "agent",
        _route_after_agent,
        {"tools": "tools", "end": END},
    )
    graph.add_conditional_edges(
        "tools",
        _route_after_tools,
        {"agent": "agent", "auto_save": "auto_save", "end": END},
    )
    graph.add_edge("auto_save", END)

    return graph.compile()
