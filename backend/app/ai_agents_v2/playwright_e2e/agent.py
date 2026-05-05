import asyncio
import json
import logging
import re
import time
from typing import Dict, Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langfuse import observe
from langfuse import get_client as get_langfuse_client

from app.core.observability import fire_evaluation, get_trace_callback
from app.llm.llm_control import create_llm
from .tools import PlaywrightMCPClient
from .prompts import MAPPING_SYSTEM, MAPPING_USER
from .config import LLM_MODEL, LLM_TEMPERATURE, APP_BASE_URL, PLACEHOLDER_PREFIX

logger = logging.getLogger(__name__)

# Keyword filter for DOM compression — keeps only lines the LLM needs
_DOM_KEYWORDS = (
    "button", "input", "label", "link", "text", "heading",
    "aria", "role", "select", "textarea", "checkbox", "radio",
    "placeholder", "name=", "value=",
)
_DOM_MAX_LINES = 150


def _compress_dom(content: str) -> str:
    """
    Filter an accessibility-tree snapshot to interactive/relevant lines only.
    Reduces browser_snapshot output from ~10k chars to ~500-2k chars.
    Falls back to first 1000 chars if nothing matches.
    """
    lines = content.splitlines()
    kept = [l for l in lines if any(kw in l.lower() for kw in _DOM_KEYWORDS)]
    if not kept:
        return content[:1000]
    if len(kept) > _DOM_MAX_LINES:
        kept = kept[:_DOM_MAX_LINES]
        kept.append(f"... [{len(lines) - _DOM_MAX_LINES} more lines filtered]")
    return "\n".join(kept)


class PlaywrightReActAgent:
    """
    Two-phase Playwright agent.

    Phase 1 — 1 LLM call:
        Navigate → ONE snapshot → LLM maps ALL placeholders to real locators

    Phase 2 — pure Python:
        Apply mapping to script_v1 → script_v2  (zero LLM calls)

    Replaces the old ReAct loop (10-15 LLM calls) with 1-2 calls total,
    eliminating the Groq TPM rate-limit problem.
    """

    @observe(name="playwright_two_phase_agent")
    async def run(
        self,
        script_v1: str,
        app_url: str = APP_BASE_URL,
        test_case_id: Optional[str] = None,
        headless: Optional[bool] = None,
        browser: Optional[str] = None,
    ) -> Dict[str, Any]:
        start = time.time()
        actual_headless = headless if headless is not None else True
        actual_browser = browser if browser is not None else "chromium"

        get_langfuse_client().update_current_span(
            input={"script_v1": script_v1, "app_url": app_url, "test_case_id": test_case_id},
            metadata={"browser": actual_browser, "headless": actual_headless},
        )

        logger.info(f"Two-phase agent — browser={actual_browser}, headless={actual_headless}")
        logger.info(f"App URL: {app_url}")

        # Extract unique placeholders, preserving order
        placeholders = list(dict.fromkeys(
            re.findall(rf'\[{PLACEHOLDER_PREFIX}: ([^\]]+)\]', script_v1)
        ))

        if not placeholders:
            logger.info("No placeholders found — returning script as-is")
            return self._result(script_v1, "completed", 0, 0, 0, None, time.time() - start)

        logger.info(f"Placeholders to resolve ({len(placeholders)}): {placeholders}")

        # ── Phase 1: browser work (navigate + ONE snapshot) ─────────────────────
        async with PlaywrightMCPClient(headless=actual_headless, browser=actual_browser) as mcp:
            tools = {t.name: t for t in mcp.tools}

            if not {"browser_navigate", "browser_snapshot"}.issubset(tools):
                return self._result(
                    script_v1, "error", 0, 0, len(placeholders),
                    "Required MCP tools (browser_navigate, browser_snapshot) not available",
                    time.time() - start,
                )

            try:
                logger.info("Navigating to app...")
                await tools["browser_navigate"].ainvoke({"url": app_url})

                logger.info("Taking DOM snapshot...")
                raw_snapshot = str(await tools["browser_snapshot"].ainvoke({}))
                dom = _compress_dom(raw_snapshot)
                logger.info(f"DOM compressed: {len(raw_snapshot)} → {len(dom)} chars")

            except Exception as e:
                logger.error(f"Browser phase failed: {e}", exc_info=True)
                return self._result(script_v1, "error", 0, 0, len(placeholders), str(e), time.time() - start)

        # ── Phase 2: ONE LLM call — map all placeholders ────────────────────────
        try:
            llm = create_llm(temperature=LLM_TEMPERATURE, model=LLM_MODEL)
            mapping = await self._resolve_placeholders(llm, placeholders, dom)
            logger.info(f"Mapping resolved: {len(mapping)}/{len(placeholders)} placeholders")
        except Exception as e:
            logger.error(f"LLM mapping failed: {e}", exc_info=True)
            return self._result(script_v1, "error", 0, 0, len(placeholders), str(e), time.time() - start)

        # ── Phase 3: apply mapping — pure Python, zero LLM calls ────────────────
        script_v2 = self._apply_mapping(script_v1, mapping)
        remaining = len(re.findall(rf'\[{PLACEHOLDER_PREFIX}:', script_v2))
        resolved = len(placeholders) - remaining
        status = "completed" if remaining == 0 else "partial"

        logger.info(f"Script v2 ready — {resolved}/{len(placeholders)} resolved, status={status}")

        result = self._result(
            script_v2, status,
            steps_passed=resolved,
            steps_failed=0,
            remaining=remaining,
            error=None if remaining == 0 else f"{remaining} placeholder(s) could not be resolved",
            duration=time.time() - start,
        )

        lf = get_langfuse_client()
        lf.update_current_span(
            output={
                "execution_status": result["execution_status"],
                "steps_passed": result["steps_passed"],
                "remaining_placeholders": result["remaining_placeholders"],
                "duration": round(result["duration"], 2),
            },
            metadata={"test_case_id": test_case_id, "total_placeholders": len(placeholders)},
        )

        # Fire DeepEval quality check in background when the script is complete/partial
        if result["execution_status"] in ("completed", "partial"):
            trace_id = lf.get_current_trace_id()
            asyncio.create_task(fire_evaluation(
                metric="playwright_script_quality",
                input_text=script_v1,
                output_text=result["script_v2"],
                trace_id=trace_id,
            ))

        return result

    # ── helpers ─────────────────────────────────────────────────────────────────

    async def _resolve_placeholders(self, llm, placeholders: list, dom: str) -> dict:
        """Single LLM call: compressed DOM + placeholder list → JSON locator mapping."""
        cb = get_trace_callback()
        invoke_config = {"callbacks": [cb]} if cb else {}
        response = await llm.ainvoke(
            [
                SystemMessage(content=MAPPING_SYSTEM),
                HumanMessage(content=MAPPING_USER.format(
                    dom=dom,
                    placeholders=json.dumps(placeholders, indent=2),
                )),
            ],
            config=invoke_config,
        )

        content = response.content.strip()

        # Strip markdown code fences if the model wrapped the JSON
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            content = match.group(0)

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse locator mapping JSON: {e}. Raw: {content[:300]}")
            return {}

    def _apply_mapping(self, script: str, mapping: dict) -> str:
        """
        Replace every page.locator("[PLACEHOLDER: desc]") with the real locator.
        Pure Python — no LLM involved.
        """
        result = script
        for description, locator in mapping.items():
            old = f'page.locator("[{PLACEHOLDER_PREFIX}: {description}]")'
            result = result.replace(old, locator)
        return result

    def _result(
        self,
        script_v2: str,
        status: str,
        steps_passed: int,
        steps_failed: int,
        remaining: int,
        error: Optional[str],
        duration: float,
    ) -> Dict[str, Any]:
        return {
            "script_v2": script_v2,
            "execution_status": status,
            "steps_passed": steps_passed,
            "steps_failed": steps_failed,
            "remaining_placeholders": remaining,
            "error": error,
            "duration": duration,
        }


# ============================================================
# HELPER FUNCTIONS FOR TOOL RESULT FORMATTING (kept for other callers)
# ============================================================

def format_tool_result(tool_name: str, output) -> str:
    """Formats an MCP tool result for display."""
    output_str = _extract_text_from_mcp_response(output)

    error_keywords = ("exception", "failed", "timeout", "not found", "unable to", "error:")
    is_error = any(kw in output_str.lower() for kw in error_keywords) or "❌" in output_str

    if is_error:
        return f"❌ Error: {output_str[:200].strip()}"

    if tool_name == "browser_navigate":
        return "✅ Page loaded"
    elif tool_name == "browser_click":
        return "✅ Clicked"
    elif tool_name in ("browser_type", "browser_fill"):
        return "✅ Field filled"
    elif tool_name == "browser_snapshot":
        return f"✅ DOM captured ({output_str.count(chr(10)) + 1} lines)"
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
    """Extracts plain text from an MCP response (may be str, list, or dict)."""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        texts = []
        for item in output:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif "text" in item:
                    texts.append(str(item["text"]))
                elif "content" in item:
                    texts.append(_extract_text_from_mcp_response(item["content"]))
            else:
                texts.append(str(item))
        return " ".join(texts) if texts else ""
    if isinstance(output, dict):
        if "text" in output:
            return str(output["text"])
        if "content" in output:
            return _extract_text_from_mcp_response(output["content"])
    return str(output)
