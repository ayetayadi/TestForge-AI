"""
ReAct agent node factory, adapted for TestForge-AI (OpenRouter backend).
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Any, Callable, Dict, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from openai import OpenAI, BadRequestError, APIStatusError

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_MODEL       = "openai/gpt-4o-mini"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


# ── Schema helpers ─────────────────────────────────────────────────────────────

def _inline_refs(schema: dict) -> dict:
    schema = copy.deepcopy(schema)
    defs   = schema.pop("$defs", {})

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].split("/")[-1]
                return _resolve(copy.deepcopy(defs.get(ref_name, {})))
            return {k: _resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_resolve(i) for i in node]
        return node

    return _resolve(schema)


def _strip_titles(schema: dict) -> dict:
    if isinstance(schema, dict):
        schema.pop("title", None)
        for v in schema.values():
            _strip_titles(v)
    elif isinstance(schema, list):
        for item in schema:
            _strip_titles(item)
    return schema


def _tools_to_openai_format(tools: list) -> List[dict]:
    result = []
    for t in tools:
        if t.args_schema:
            schema = t.args_schema.model_json_schema()
            schema = _inline_refs(schema)
            schema = _strip_titles(schema)
        else:
            schema = {"type": "object", "properties": {}, "required": []}

        result.append({
            "type": "function",
            "function": {
                "name":        t.name,
                "description": (t.description or "").strip(),
                "parameters":  schema,
            },
        })
    return result


# ── Message converters ─────────────────────────────────────────────────────────

def _lc_to_openai(msg) -> dict:
    content = msg.content if isinstance(msg.content, str) else str(msg.content)

    if isinstance(msg, SystemMessage):
        return {"role": "system", "content": content}
    if isinstance(msg, HumanMessage):
        return {"role": "user", "content": content}
    if isinstance(msg, AIMessage):
        entry: Dict[str, Any] = {"role": "assistant", "content": content or ""}
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            entry["tool_calls"] = [
                {
                    "id":   tc["id"],
                    "type": "function",
                    "function": {
                        "name":      tc["name"],
                        "arguments": json.dumps(tc.get("args", {})),
                    },
                }
                for tc in tool_calls
            ]
        return entry
    if isinstance(msg, ToolMessage):
        return {
            "role":         "tool",
            "tool_call_id": msg.tool_call_id,
            "content":      content,
        }
    return {"role": "user", "content": content}


def _openai_to_ai_message(choice) -> AIMessage:
    msg          = choice.message
    text_content = msg.content or ""
    tool_calls: List[dict] = []

    for tc in (msg.tool_calls or []):
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        tool_calls.append({
            "id":   tc.id,
            "name": tc.function.name,
            "args": args,
            "type": "tool_call",
        })

    return AIMessage(content=text_content, tool_calls=tool_calls)


# ── State-aware expected-next-tool helper ──────────────────────────────────────

def _expected_next_tool(state: dict, llm_tool_names: set) -> Optional[str]:
    """
    Returns the tool the agent should call next, or None if auto-save handles it.
    Used only as a fallback when the model responds with text and no tool call.
    """
    if not state.get("test_cases_structured"):
        return "draft_test_cases"
    critique = state.get("critique_result") or {}
    if not critique.get("quality_ok", True) and "refine_test_cases" in llm_tool_names:
        messages = state.get("messages") or []
        refine_rounds = sum(
            1
            for msg in messages
            for tc in (getattr(msg, "tool_calls", None) or [])
            if tc.get("name") == "refine_test_cases"
        )
        if refine_rounds < 2:
            return "refine_test_cases"
    return None  # auto-save handles terminal steps


def _build_retry_nudge(next_tool: str) -> str:
    nudges = {
        "draft_test_cases":  "Analysis is complete. Now call draft_test_cases with your initial comprehensive test cases.",
        "refine_test_cases": "Critique is done. Now call refine_test_cases with the improved complete set of test cases addressing all issues listed.",
    }
    return nudges.get(next_tool, f"Please call {next_tool} now to continue.")


# ── Factory ────────────────────────────────────────────────────────────────────

def make_agent_node(
    tools:                list,
    build_prompt_fn:      Callable[[dict], str],
    max_completion_tokens: int = 4096,
) -> Callable[[dict], Dict[str, Any]]:
    openai_tools_schema = _tools_to_openai_format(tools)
    llm_tool_names = {t.name for t in tools}

    def agent_node(state: dict) -> Dict[str, Any]:
        api_key = settings.OPENROUTER_API_KEY
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not configured in settings")

        client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)

        system_prompt   = build_prompt_fn(state)
        openai_messages = [{"role": "system", "content": system_prompt}]

        # Keep only the first message (initial task) + the 6 most recent messages.
        # The system prompt already carries full state (analysis, critique, progress),
        # so old history is redundant and just burns tokens.
        all_lc = state.get("messages") or []
        if len(all_lc) > 7:
            lc_msgs_to_send = all_lc[:1] + all_lc[-6:]
        else:
            lc_msgs_to_send = all_lc

        for lc_msg in lc_msgs_to_send:
            entry = _lc_to_openai(lc_msg)
            # Truncate large tool results (draft/refine args are already in state)
            if entry.get("role") == "tool" and isinstance(entry.get("content"), str):
                if len(entry["content"]) > 800:
                    entry["content"] = entry["content"][:800] + "\n... [truncated]"
            # Summarise large AI tool-call args (test case lists) in older messages
            if entry.get("role") == "assistant" and entry.get("tool_calls"):
                for tc in entry["tool_calls"]:
                    fn = tc.get("function", {})
                    if fn.get("name") in ("draft_test_cases", "refine_test_cases", "save_test_cases"):
                        try:
                            args  = json.loads(fn["arguments"])
                            count = len(args.get("test_cases") or [])
                            fn["arguments"] = json.dumps({
                                "_summary": f"{count} test cases (full data in agent state)",
                                "changes_summary": args.get("changes_summary", ""),
                            })
                        except Exception:
                            pass
            openai_messages.append(entry)

        selected_model = state.get("model") or DEFAULT_MODEL

        # For deterministic steps, force the specific tool — skips model reasoning entirely.
        has_draft = bool(state.get("test_cases_structured"))
        critique  = state.get("critique_result") or {}
        if not has_draft:
            forced_tool = "draft_test_cases"
        elif not critique.get("quality_ok", True):
            messages_so_far = state.get("messages") or []
            refine_rounds = sum(
                1 for msg in messages_so_far
                for tc in (getattr(msg, "tool_calls", None) or [])
                if tc.get("name") == "refine_test_cases"
            )
            forced_tool = "refine_test_cases" if refine_rounds < 2 else None
        else:
            forced_tool = None

        resolved_tool_choice = (
            {"type": "function", "function": {"name": forced_tool}}
            if forced_tool else "required"
        )

        call_kwargs: Dict[str, Any] = dict(
            messages    = openai_messages,
            tools       = openai_tools_schema,
            tool_choice = resolved_tool_choice,
            temperature = 0.0,
            max_tokens  = max_completion_tokens,
        )

        try:
            response = client.chat.completions.create(model=selected_model, **call_kwargs)
        except (BadRequestError, APIStatusError) as exc:
            msg_str = str(exc).lower()
            is_token_err = any(kw in msg_str for kw in (
                "context_length_exceeded", "maximum context length",
                "reduce the length", "token", "too long",
            ))
            if not is_token_err:
                raise
            logger.warning("[agent_node] Token limit hit — retrying with truncated context")
            call_kwargs["messages"] = openai_messages[:4]
            response = client.chat.completions.create(model=selected_model, **call_kwargs)

        ai_message = _openai_to_ai_message(response.choices[0])
        thought    = (response.choices[0].message.content or "").strip()

        # ── Fallback: model wrote text but skipped the tool call ───────────────
        # tool_choice="required" may be ignored by some OpenRouter providers.
        if not ai_message.tool_calls and not state.get("approved") and not state.get("flagged_for_human"):
            next_tool = _expected_next_tool(state, llm_tool_names)
            if next_tool is None:
                # Auto-save will handle the terminal step — no retry needed.
                logger.info("[agent_node] No tool call and auto-save covers terminal step; skipping retry.")
            else:
                nudge = _build_retry_nudge(next_tool)
                logger.warning("[agent_node] No tool call — retrying with forced %s", next_tool)
                retry_messages = openai_messages + [
                    {"role": "assistant", "content": thought or "(no content)"},
                    {"role": "user",      "content": nudge},
                ]
                retry_kwargs = dict(
                    messages    = retry_messages,
                    tools       = openai_tools_schema,
                    tool_choice = {"type": "function", "function": {"name": next_tool}},
                    temperature = 0.0,
                    max_tokens  = max_completion_tokens,
                )
                try:
                    retry_resp = client.chat.completions.create(model=selected_model, **retry_kwargs)
                    ai_message = _openai_to_ai_message(retry_resp.choices[0])
                    thought    = (retry_resp.choices[0].message.content or "").strip()
                except Exception as retry_exc:
                    logger.error("[agent_node] Forced retry failed: %s", retry_exc)

        # ── Build execution trace ──────────────────────────────────────────────
        tool_calls_list = ai_message.tool_calls or []
        log = list(state.get("thought_action_log") or [])
        if tool_calls_list:
            for tc in tool_calls_list:
                log.append({
                    "type":    "thought",
                    "content": thought,
                    "action":  tc.get("name", "unknown"),
                })
        elif thought:
            log.append({"type": "thought", "content": thought, "action": None})

        return {"messages": [ai_message], "thought_action_log": log}

    return agent_node
