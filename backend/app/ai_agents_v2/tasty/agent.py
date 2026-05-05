"""
Tasty orchestrator — a ReAct agent that uses existing TestForge AI agents as tools.
"""
from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.core.config import settings
from app.ai_agents_v2.tasty.prompts import build_system_prompt
from app.ai_agents_v2.tasty.tools.query_tools import make_query_tools
from app.ai_agents_v2.tasty.tools.action_tools import make_action_tools

logger = logging.getLogger(__name__)


def create_tasty_agent(user_id: str):
    """
    Build the Tasty ReAct orchestrator for the given user.
    Uses OpenRouter (gpt-4o-mini) for conversational quality + tool calling.
    """
    if not settings.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")

    llm = ChatOpenAI(
        model="openai/gpt-4o-mini",
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        temperature=0.3,
        max_tokens=1500,
        streaming=True,
    )

    tools = make_query_tools(user_id) + make_action_tools(user_id)
    system_prompt = build_system_prompt(user_id)

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
    )

    logger.info("[Tasty] Agent created for user=%s with %d tools", user_id, len(tools))
    return agent
