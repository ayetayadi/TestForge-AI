"""
Tasty AI Testing Assistant — SSE streaming chat endpoint.
POST /chatbot/message  →  streams Server-Sent Events:
  { type: "token",      content: "..." }
  { type: "tool_start", tool: "get_projects", input: "..." }
  { type: "tool_end",   tool: "get_projects" }
  { type: "done" }
  { type: "error",      content: "..." }
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.models.user import User
from app.ai_agents_v2.tasty.agent import create_tasty_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chatbot", tags=["Tasty"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/message")
async def chat_message(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """Stream a Tasty AI response as Server-Sent Events."""
    user_id = str(current_user.id)

    try:
        agent = create_tasty_agent(user_id=user_id)
    except RuntimeError as exc:
        async def _err():
            yield _sse({"type": "error", "content": str(exc)})
        return StreamingResponse(_err(), media_type="text/event-stream", headers=_SSE_HEADERS)

    input_messages = {"messages": [{"role": "user", "content": payload.message}]}

    async def event_stream():
        try:
            async for event in agent.astream_events(input_messages, version="v2"):
                kind = event.get("event", "")

                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk and getattr(chunk, "content", None):
                        yield _sse({"type": "token", "content": chunk.content})

                elif kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    tool_input = event["data"].get("input", {})
                    yield _sse({
                        "type": "tool_start",
                        "tool": tool_name,
                        "input": str(tool_input)[:300],
                    })

                elif kind == "on_tool_end":
                    yield _sse({"type": "tool_end", "tool": event.get("name", "")})

            yield _sse({"type": "done"})

        except Exception as exc:
            logger.exception("[Tasty] Streaming error for user=%s: %s", user_id, exc)
            yield _sse({"type": "error", "content": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/health")
async def tasty_health():
    """Quick liveness check for the Tasty endpoint."""
    return {"status": "ok", "assistant": "Tasty"}
