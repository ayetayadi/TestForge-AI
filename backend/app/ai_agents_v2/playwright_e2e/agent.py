import logging
import re
import time
from typing import Dict, Any, Optional

from langgraph.prebuilt import create_react_agent
from langsmith import traceable

from app.llm.llm_control import create_llm
from .tools import PlaywrightMCPClient
from .prompts import REACT_SYSTEM, REACT_USER
from .config import LLM_MODEL, LLM_TEMPERATURE, MAX_REACT_ITERATIONS, APP_BASE_URL, PLACEHOLDER_PREFIX

logger = logging.getLogger(__name__)


class PlaywrightReActAgent:
    """
    ReAct Agent for E2E test execution via MCP Playwright.
    Supports TypeScript Playwright scripts.
    """

    @traceable(name="playwright_react_agent")
    async def run(self, script_v1: str, app_url: str = APP_BASE_URL, test_case_id: Optional[str] = None, headless: Optional[bool] = None, browser: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute Script v1 against the real app and produce Script v2.
        """

        start_time = time.time()
        actual_headless = headless if headless is not None else True
        actual_browser = browser if browser is not None else "chromium"
        
        logger.info(f"🎯 ReAct Agent - Browser: {actual_browser}, Headless: {actual_headless}")
        logger.info(f"📝 Values from user - headless: {headless}, browser: {browser}")
        
        logger.info("🔍 DEBUG: === AGENT RUN START ===")
        logger.info(f"PlaywrightReActAgent starting")
        logger.info(f"App URL: {app_url}")
        logger.info(f"Placeholders found: {script_v1.count(f'[{PLACEHOLDER_PREFIX}:')}")
    
        logger.info("🔍 DEBUG: Creating MCP client...")

        async with PlaywrightMCPClient(
            headless=actual_headless, 
            browser=actual_browser,
        ) as mcp:
            logger.info(f"🔍 DEBUG: MCP client created. Tools available: {len(mcp.tools)}")
            logger.info(f"🔍 DEBUG: Tool names: {[t.name for t in mcp.tools]}")
        
            if len(mcp.tools) == 0:
                logger.error("🔍 DEBUG: NO TOOLS AVAILABLE! Agent cannot do anything.")
                return {
                    "script_v2": script_v1,
                    "execution_status": "no_tools",
                    "steps_passed": 0,
                    "steps_failed": 0,
                    "error": "No MCP tools loaded. Check MCP server connection.",
                }
            llm = create_llm(temperature=LLM_TEMPERATURE, model=LLM_MODEL)
            logger.info("🔍 DEBUG: LLM created")

            from langgraph.prebuilt import ToolNode
            from langchain_core.tools.base import ToolException

            def _handle_mcp_error(e: Exception) -> str:
                if isinstance(e, ToolException):
                    return f"Tool error (recoverable): {str(e)}. Try a different approach."
                raise e

            tool_node = ToolNode(mcp.tools, handle_tool_errors=_handle_mcp_error)
            agent = create_react_agent(
                model=llm,
                tools=tool_node,
                prompt=REACT_SYSTEM,
            )
            logger.info("🔍 DEBUG: ReAct agent created")

            user_message = REACT_USER.format(
                script_v1=script_v1,
                app_url=app_url,
            )

            inputs = {"messages": [("user", user_message)]}
            logger.info("Invoking ReAct agent...")
            logger.info("🔍 DEBUG: Calling agent.ainvoke...")


            try:
                final_state = await agent.ainvoke(
                    inputs,
                    config={"recursion_limit": MAX_REACT_ITERATIONS},
                )
                logger.info("🔍 DEBUG: Agent.ainvoke completed")
                logger.info("🔍 FINAL STATE MESSAGES:")
                for i, msg in enumerate(final_state.get("messages", [])):
                    logger.info(f"  Message {i}: {type(msg).__name__}")
                    if hasattr(msg, "content"):
                        logger.info(f"    Content: {str(msg.content)[:500]}...")
                result = self._process_result(final_state, script_v1)
                result["duration"] = time.time() - start_time
                return result

            except Exception as e:
                logger.error(f"ReAct agent failed: {e}", exc_info=True)
                return {
                    "script_v2": script_v1,
                    "execution_status": "error",
                    "steps_passed": 0,
                    "steps_failed": 0,
                    "error": str(e),
                }

    def _process_result(self, final_state: Dict, script_v1: str) -> Dict[str, Any]:
        messages = final_state.get("messages", [])
        if not messages:
            return self._empty_result(script_v1, "no_output")

        last_message = messages[-1]
        content = (
            last_message.content
            if hasattr(last_message, "content")
            else str(last_message)
        )

        script_v2 = self._extract_script(content) or script_v1
        remaining_placeholders = script_v2.count(f"[{PLACEHOLDER_PREFIX}:")

        # Count steps from actual tool results (browser interactions)
        _error_kw = ("### error", "exception", "timeouterror", "unable to", "not found", "error:")
        tool_messages = [m for m in messages if type(m).__name__ == "ToolMessage"]
        steps_failed = sum(
            1 for m in tool_messages
            if any(kw in str(m.content).lower() for kw in _error_kw)
        )
        steps_passed = len(tool_messages) - steps_failed

        status = "passed" if steps_failed == 0 and steps_passed > 0 else (
            "failed" if steps_failed > 0 else "completed"
        )

        logger.info(f"Script v2 ready — status={status}, remaining placeholders={remaining_placeholders}")

        return {
            "script_v2": script_v2,
            "execution_status": status,
            "steps_passed": steps_passed,
            "steps_failed": steps_failed,
            "remaining_placeholders": remaining_placeholders,
            "error": None,
            "raw_messages": messages,
        }

    def _extract_script(self, content: str) -> Optional[str]:
        """Extract TypeScript code block from agent response."""
        
        # Cherche bloc TypeScript
        match = re.search(r"```typescript\s*(.*?)```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Cherche bloc JavaScript/TS
        match = re.search(r"```(?:js|javascript|ts)\s*(.*?)```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Cherche bloc sans langage spécifié
        match = re.search(r"```\s*(.*?)```", content, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # Vérifie si le contenu ressemble directement à du TypeScript Playwright
        if "import { test, expect } from '@playwright/test'" in content:
            return content.strip()
        
        if "test('" in content and "async ({ page })" in content:
            return content.strip()
        
        return None

    def _empty_result(self, script_v1: str, reason: str) -> Dict[str, Any]:
        return {
            "script_v2": script_v1,
            "execution_status": reason,
            "steps_passed": 0,
            "steps_failed": 0,
            "remaining_placeholders": script_v1.count(f"[{PLACEHOLDER_PREFIX}:"),
            "error": f"Agent returned no output: {reason}",
        }


# ============================================================
# HELPER FUNCTIONS FOR TOOL RESULT FORMATTING
# ============================================================

def format_tool_result(tool_name: str, output) -> str:
    """Formatte le résultat d'un outil MCP pour l'affichage."""
    
    output_str = _extract_text_from_mcp_response(output)
    
    # Vérifie les vraies erreurs
    error_keywords = ("exception", "failed", "timeout", "not found", "unable to", "error:")
    is_error = any(kw in output_str.lower() for kw in error_keywords)
    
    if "❌" in output_str:
        is_error = True

    if is_error:
        short = output_str[:200].strip()
        return f"❌ Error: {short}"

    # Formatage selon le type d'outil
    if tool_name == "browser_navigate":
        return "✅ Page loaded"
    elif tool_name == "browser_click":
        return "✅ Clicked"
    elif tool_name == "browser_type" or tool_name == "browser_fill":
        return "✅ Field filled"
    elif tool_name == "browser_fill_form":
        return "✅ Form filled"
    elif tool_name == "browser_snapshot":
        lines = output_str.count("\n") + 1
        return f"✅ DOM captured ({lines} lines)"
    #elif tool_name == "browser_verify_element_visible":
    #    return "✅ Element visible"
    #elif tool_name == "browser_verify_text_visible":
    #    return "✅ Text visible"
    #elif tool_name == "browser_generate_locator":
    #    return f"✅ Locator: {output_str[:100]}"
    elif tool_name == "browser_wait_for":
        return "✅ Wait completed"
    elif tool_name == "browser_select_option":
        return "✅ Option selected"
    elif tool_name == "browser_press_key":
        return "✅ Key pressed"
    elif tool_name == "browser_take_screenshot":
        return "✅ Screenshot saved"
    
    return f"✅ {output_str[:100]}"


def _extract_text_from_mcp_response(output) -> str:
    """Extrait le texte d'une réponse MCP (qui peut être une liste de dicts)."""
    
    if isinstance(output, str):
        return output
    
    if isinstance(output, list):
        texts = []
        for item in output:
            if isinstance(item, dict):
                if item.get('type') == 'text':
                    texts.append(item.get('text', ''))
                elif 'text' in item:
                    texts.append(str(item['text']))
                elif 'content' in item:
                    texts.append(_extract_text_from_mcp_response(item['content']))
            else:
                texts.append(str(item))
        if texts:
            return ' '.join(texts)
    
    if isinstance(output, dict):
        if 'text' in output:
            return str(output['text'])
        if 'content' in output:
            return _extract_text_from_mcp_response(output['content'])
    
    return str(output)