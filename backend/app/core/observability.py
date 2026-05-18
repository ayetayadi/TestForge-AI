"""
Observability: LangSmith tracing.

LangSmith setup
---------------
  Required env vars (in backend/.env):
    LANGCHAIN_TRACING_V2=true
    LANGCHAIN_API_KEY=<your LangSmith API key>
    LANGCHAIN_PROJECT=<project name shown in LangSmith UI>

  When LANGCHAIN_TRACING_V2=true, LangChain automatically traces every
  LLM call to LangSmith — no manual callback wiring needed.

Usage in the codebase
---------------------
  from langsmith import traceable

  @traceable(name="my_pipeline", run_type="chain")
  async def run(self, ...):
      ...
"""
import logging
import os

logger = logging.getLogger(__name__)

_langsmith_enabled = False


def init_langsmith() -> None:
    """
    Verify LangSmith connectivity and mark the integration as enabled.

    Reads LANGSMITH_API_KEY + LANGSMITH_TRACING from env (set by load_dotenv()
    in main.py). Also accepts LANGCHAIN_API_KEY + LANGCHAIN_TRACING_V2 as aliases.
    """
    global _langsmith_enabled
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    tracing = (
        os.getenv("LANGSMITH_TRACING", "")
        or os.getenv("LANGCHAIN_TRACING_V2", "")
    ).lower()
    if not api_key or tracing not in ("true", "1"):
        logger.info("[LANGSMITH] Tracing disabled (LANGSMITH_API_KEY or LANGSMITH_TRACING not set)")
        return
    try:
        from langsmith import Client
        client = Client(api_key=api_key)
        list(client.list_projects(limit=1))
        _langsmith_enabled = True
        project = os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT", "default")
        logger.info("[LANGSMITH] Auth OK — tracing enabled (project=%s)", project)
    except Exception as exc:
        logger.warning("[LANGSMITH] Init failed: %s", exc)


def is_langsmith_enabled() -> bool:
    return _langsmith_enabled
