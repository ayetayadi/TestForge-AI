"""Assembled TestCaseGenerator graph."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from app.ai_agents_v2.test_case_generator.agent_node  import make_agent_node
from app.ai_agents_v2.test_case_generator.tool_node   import make_tool_node
from app.ai_agents_v2.test_case_generator.react_graph import build_react_graph
from app.ai_agents_v2.test_case_generator.state       import TestCaseAgentState
from app.ai_agents_v2.test_case_generator.prompts     import build_test_case_prompt
from app.ai_agents_v2.test_case_generator.tools       import ALL_TOOLS, LLM_TOOLS, TERMINAL_TOOLS

logger = logging.getLogger(__name__)


def _to_dict_list(raw: list) -> list:
    """Normalise a list that may contain Pydantic models or plain dicts."""
    result = []
    for item in raw:
        if isinstance(item, dict):
            result.append(item)
        elif hasattr(item, "model_dump"):
            result.append(item.model_dump())
        else:
            result.append({"raw": str(item)})
    return result


def _state_update(tool_name: str, tool_args: dict, tool_result: str) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}

    # ── Phase 1: story analysis ────────────────────────────────────────────────
    if tool_name == "analyze_story":
        try:
            updates["analysis_result"] = json.loads(tool_result)
        except (json.JSONDecodeError, ValueError):
            updates["analysis_result"] = {"raw": tool_result}

    # ── Phase 2: initial draft (critique embedded in tool result) ─────────────
    elif tool_name == "draft_test_cases":
        raw = tool_args.get("test_cases") or []
        updates["test_cases_structured"] = _to_dict_list(raw)
        try:
            result_dict = json.loads(tool_result)
            if "critique" in result_dict:
                updates["critique_result"] = result_dict["critique"]
        except (json.JSONDecodeError, ValueError):
            pass

    # ── Phase 3: explicit critique (fallback) ─────────────────────────────────
    elif tool_name == "critique_test_cases":
        try:
            updates["critique_result"] = json.loads(tool_result)
        except (json.JSONDecodeError, ValueError):
            updates["critique_result"] = {"raw": tool_result, "quality_ok": False}

    # ── Phase 4: refinement (critique embedded in tool result) ────────────────
    elif tool_name == "refine_test_cases":
        raw = tool_args.get("test_cases") or []
        updates["test_cases_structured"] = _to_dict_list(raw)
        try:
            result_dict = json.loads(tool_result)
            if "critique" in result_dict:
                updates["critique_result"] = result_dict["critique"]
        except (json.JSONDecodeError, ValueError):
            pass

    # ── Terminal: save ─────────────────────────────────────────────────────────
    elif tool_name == "save_test_cases":
        raw = tool_args.get("test_cases") or []
        updates["test_cases_structured"] = _to_dict_list(raw)

        raw_analysis = tool_args.get("user_story_analysis") or {}
        updates["user_story_analysis"] = (
            raw_analysis if isinstance(raw_analysis, dict)
            else raw_analysis.model_dump()
        )
        updates["approved"] = True
        try:
            updates["saved_paths"] = json.loads(tool_result).get("paths", {})
        except (json.JSONDecodeError, ValueError):
            updates["saved_paths"] = {}

    # ── Terminal: flag ─────────────────────────────────────────────────────────
    elif tool_name == "flag_human_review":
        updates["flagged_for_human"] = True
        draft = tool_args.get("draft_cases") or []
        if draft:
            updates["test_cases_structured"] = _to_dict_list(draft)

    return updates


_agent_node = make_agent_node(
    tools=LLM_TOOLS,           # Only the 3 tools the LLM can actually call
    build_prompt_fn=build_test_case_prompt,
    max_completion_tokens=4096,
)

_tool_node = make_tool_node(
    tools=ALL_TOOLS,            # Full set for dispatch (includes auto-save targets)
    state_update_fn=_state_update,
)

compiled_test_case_graph = build_react_graph(
    state_class=TestCaseAgentState,
    agent_node=_agent_node,
    tool_node=_tool_node,
    terminal_tools=TERMINAL_TOOLS,
)
