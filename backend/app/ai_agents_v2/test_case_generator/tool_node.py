"""Generic ReAct tool node factory."""
from __future__ import annotations

import json
import logging
import traceback
from typing import Any, Callable, Dict, Optional

from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)


def make_tool_node(
    tools: list,
    state_update_fn: Optional[Callable[[str, dict, str], Dict[str, Any]]] = None,
) -> Callable[[dict], Dict[str, Any]]:
    _tool_map = {t.name: t for t in tools}

    def tool_node(state: dict) -> Dict[str, Any]:
        messages = list(state.get("messages") or [])

        last_ai = None
        for msg in reversed(messages):
            if getattr(msg, "tool_calls", None):
                last_ai = msg
                break

        if not last_ai:
            return {}

        new_messages = []
        domain_updates: Dict[str, Any] = {}
        log = list(state.get("thought_action_log") or [])

        for tc in (last_ai.tool_calls or []):
            tool_name: str = tc.get("name", "")
            tool_args: Dict[str, Any] = dict(tc.get("args") or {})
            tool_call_id: str = tc.get("id", "")

            raw_result = _invoke_tool(tool_name, tool_args, _tool_map)

            new_messages.append(ToolMessage(
                content=raw_result,
                tool_call_id=tool_call_id,
                name=tool_name,
            ))

            preview = raw_result[:300] + ("..." if len(raw_result) > 300 else "")
            log.append({"type": "observation", "tool": tool_name, "result": preview})

            if state_update_fn:
                try:
                    updates = state_update_fn(tool_name, tool_args, raw_result)
                    if updates:
                        domain_updates.update(updates)
                except Exception as exc:
                    logger.error("[tool_node] state_update_fn raised for %s: %s", tool_name, exc)

        domain_updates["messages"] = new_messages
        domain_updates["thought_action_log"] = log
        return domain_updates

    return tool_node


def _sanitize_args(tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean up common LLM hallucination patterns before Pydantic validation.
    The LLM occasionally appends non-dict items (e.g. a stray acceptance_criteria
    string) as the last element of a test_cases array.
    """
    if tool_name in ("draft_test_cases", "refine_test_cases", "save_test_cases", "critique_test_cases"):
        raw_tcs = tool_args.get("test_cases")
        if isinstance(raw_tcs, list):
            tool_args = dict(tool_args)
            tool_args["test_cases"] = [tc for tc in raw_tcs if isinstance(tc, dict)]
            dropped = len(raw_tcs) - len(tool_args["test_cases"])
            if dropped:
                logger.warning(
                    "[tool_node] %s: dropped %d non-dict item(s) from test_cases",
                    tool_name, dropped,
                )
    return tool_args


def _invoke_tool(tool_name: str, tool_args: Dict[str, Any], tool_map: dict) -> str:
    tool = tool_map.get(tool_name)
    if not tool:
        return json.dumps({"error": f"Unknown tool: {tool_name!r}"})

    tool_args = _sanitize_args(tool_name, tool_args)

    try:
        result = tool.invoke(tool_args)
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("[tool_node] %s raised: %s\n%s", tool_name, exc, tb)
        return json.dumps({"error": str(exc)})
