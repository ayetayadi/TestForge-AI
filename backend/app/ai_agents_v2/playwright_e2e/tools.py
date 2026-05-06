# ============================================================
# ai_agents_v2/playwright_e2e/tools.py
# ============================================================

import asyncio
import logging
import sys
import time
from typing import List

from langchain_core.tools import BaseTool

from .config import MCP_PLAYWRIGHT_SERVER_URL

logger = logging.getLogger(__name__)


# ============================================================
# CONCURRENCY GUARD
# ============================================================

_execution_semaphore = asyncio.Semaphore(1)


# ============================================================
# WHITELISTED TOOLS
# ============================================================

ALLOWED_TOOLS = {
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_wait_for",
    "browser_press_key",
    "browser_select_option",
    "browser_tabs",
    "browser_close",
    "browser_take_screenshot"
}

_MAX_SSE_RETRIES = 1          # 1 seule tentative SSE — inutile de retenter si le serveur est down
_RETRY_BASE_DELAY = 0.3


# ============================================================
# MCP CLIENT CONTEXT MANAGER
# ============================================================

class PlaywrightMCPClient:
    """
    Context manager that keeps the MCP connection alive for one test execution.
    """

    def __init__(self, timeout_seconds: int = 60, headless: bool = True, browser: str = "chromium"):
        self.timeout_seconds = timeout_seconds
        self._session_ctx = None   # the async context manager keeping the MCP session alive
        self._lock_acquired = False
        self._transport_used: str = "unknown"
        self._start_time: float = 0.0
        self.tools: List[BaseTool] = []
        self.headless = headless
        self.browser = browser

    async def __aenter__(self):
        logger.info("🔍 DEBUG: === ENTERING MCP CLIENT ===")
        self._start_time = time.time()
        
        try:
            logger.info("🔍 DEBUG: Acquiring semaphore lock...")
            await asyncio.wait_for(_execution_semaphore.acquire(), timeout=self.timeout_seconds)
            self._lock_acquired = True
            logger.info(f"Execution lock acquired (timeout={self.timeout_seconds}s)")
        except asyncio.TimeoutError:
            logger.error(
                f"Timeout while waiting for execution lock ({self.timeout_seconds}s). "
                f"Consider increasing timeout_seconds if your tests take longer."
            )
            raise    

        try:
            logger.info("🔍 DEBUG: Calling _connect_with_fallback...")
            await self._connect_with_fallback()
            logger.info(f"✅ Connection successful, transport={self._transport_used}")
            logger.info(f"🔍 DEBUG: Tools loaded = {len(self.tools)}")
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            _execution_semaphore.release()
            self._lock_acquired = False
            raise
        
        logger.info("🔍 DEBUG: === MCP CLIENT READY ===")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self._start_time
        error_name = exc_type.__name__ if exc_type else 'None'

        logger.info(
            f"MCP connection closing - transport={self._transport_used}, "
            f"duration={duration:.2f}s, error={error_name}"
        )

        if self._session_ctx is not None:
            try:
                await self._session_ctx.__aexit__(exc_type, exc_val, exc_tb)
                logger.info("MCP session context closed")
            except Exception as e:
                logger.warning(f"Error closing MCP session context: {e}")
            self._session_ctx = None

        if self._lock_acquired:
            _execution_semaphore.release()
            self._lock_acquired = False
            logger.info("Execution lock released")

    # ----------------------------------------------------------
    # Connection logic
    # ----------------------------------------------------------
    async def _connect_with_fallback(self) -> None:
        """Try SSE with retries, fall back to stdio if all fail."""
        
        # 2. Essayer SSE avec retries
        delay = _RETRY_BASE_DELAY
        last_error: Exception | None = None

        for attempt in range(1, _MAX_SSE_RETRIES + 1):
            try:
                await self._connect_sse()
                self._transport_used = "sse"
                logger.info(
                    f"MCP Playwright SSE connected to {MCP_PLAYWRIGHT_SERVER_URL} "
                    f"(attempt {attempt}/{_MAX_SSE_RETRIES})"
                )
                return
            except Exception as e:
                last_error = e
                logger.warning(
                    f"SSE connection attempt {attempt}/{_MAX_SSE_RETRIES} failed: {e}"
                )
                if attempt < _MAX_SSE_RETRIES:
                    await asyncio.sleep(delay)
                    delay *= 2  # exponential backoff: 1s → 2s → 4s

        # 3. Fallback to stdio
        logger.error(
            f"All SSE attempts failed (last: {last_error}). "
            "Falling back to stdio — this spawns a local Node.js process."
        )
        await self._connect_stdio()
        self._transport_used = "stdio"

    async def _connect_sse(self) -> None:
        """Connect to MCP server via SSE transport."""
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools

        logger.info(f"🔍 DEBUG: Connecting to SSE at {MCP_PLAYWRIGHT_SERVER_URL}/sse")

        client = MultiServerMCPClient(
            {
                "playwright": {
                    "url": f"{MCP_PLAYWRIGHT_SERVER_URL}/sse",
                    "transport": "sse",
                    "timeout": 30,
                    "sse_read_timeout": 60,
                }
            }
        )

        # Enter the session context — keeps the MCP connection alive for all tool calls
        self._session_ctx = client.session("playwright")
        session = await self._session_ctx.__aenter__()

        logger.info("🔍 DEBUG: Session opened, loading tools...")
        all_tools = await load_mcp_tools(session)

        logger.info(f"🔍 DEBUG: Got {len(all_tools)} raw tools from server")
        logger.info(f"🔍 DEBUG: Raw tool names: {[t.name for t in all_tools]}")

        self.tools = [t for t in all_tools if t.name in ALLOWED_TOOLS]

        logger.info(f"🔍 DEBUG: Filtered to {len(self.tools)} tools")
        logger.info(f"🔍 DEBUG: Filtered tool names: {[t.name for t in self.tools]}")

        logger.info(
            f"Tools loaded [SSE]: "
            f"{len(self.tools)}/{len(all_tools)} active"
        )

    async def _connect_stdio(self) -> None:
        """Connect to MCP server via stdio transport."""
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools

        logger.info("🔍 DEBUG: Starting stdio connection...")

        npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
        client = MultiServerMCPClient(
            {
                "playwright": {
                    "command": npx_cmd,
                    "args": ["--yes", "@playwright/mcp"],
                    "transport": "stdio",
                }
            }
        )

        # Enter the session context — keeps the MCP connection alive for all tool calls
        self._session_ctx = client.session("playwright")
        session = await self._session_ctx.__aenter__()

        logger.info("🔍 DEBUG: Session opened, loading tools...")
        all_tools = await load_mcp_tools(session)

        logger.info(f"🔍 DEBUG: Raw tools from server: {[t.name for t in all_tools]}")

        self.tools = [t for t in all_tools if t.name in ALLOWED_TOOLS]

        logger.info(f"🔍 DEBUG: Filtered tools (in ALLOWED_TOOLS): {[t.name for t in self.tools]}")

        unavailable = ALLOWED_TOOLS - {t.name for t in self.tools}
        if unavailable:
            logger.warning(f"🔍 DEBUG: Tools in whitelist but NOT on server: {unavailable}")

        if len(self.tools) == 0:
            logger.error("🔍 DEBUG: NO TOOLS LOADED! Check ALLOWED_TOOLS vs server tools.")

        logger.info(
            f"Tools loaded [Stdio]: "
            f"{len(self.tools)}/{len(all_tools)} active — "
            f"{[t.name for t in self.tools]}"
        )