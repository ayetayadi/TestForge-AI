import asyncio
import json
import logging
import re
import time
from typing import Dict, Any, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable

from app.llm.llm_control import create_llm
from .tools import PlaywrightMCPClient
from .prompts import (
    MAPPING_SYSTEM, MAPPING_USER,
    REF_RESOLVER_SYSTEM, REF_RESOLVER_USER,
    RECOVERY_SYSTEM, RECOVERY_USER,
)
from .config import LLM_MAX_TOKENS, LLM_MODEL, LLM_TEMPERATURE, APP_BASE_URL, PLACEHOLDER_PREFIX

logger = logging.getLogger(__name__)

# Keyword filter for DOM compression — keeps only lines the LLM needs
_DOM_KEYWORDS = (
    "button", "input", "label", "link", "heading",
    "aria", "role", "select", "textarea", "checkbox", "radio",
    "placeholder", "name=", "value=", "textbox",
    "alert", "status",  # dynamic feedback elements (error messages, toasts)
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
    Merged Playwright agent — resolves locators and executes in one browser session.

    For each action in script_v1:
      - navigate  → execute immediately, invalidate DOM cache
      - wait/press → execute immediately
      - element action with placeholder → snapshot current page (once per page state),
        batch-resolve all same-page placeholders in one LLM call, then execute
      - element action with real locator → execute directly

    On element-not-found: re-snapshot + re-resolve + retry once.

    Result includes script_v2 (placeholders replaced with real locators) and
    locator_mapping (dict passed back to the service to persist on TestCase).
    """

    @traceable(name="playwright_merged_agent", run_type="chain")
    async def run(
        self,
        script_v1: str,
        app_url: str = APP_BASE_URL,
        test_case_id: Optional[str] = None,
        headless: Optional[bool] = None,
        browser: Optional[str] = None,
        on_step=None,
    ) -> Dict[str, Any]:
        start = time.time()
        actual_headless = headless if headless is not None else True
        actual_browser = browser if browser is not None else "chromium"

        logger.info(f"Merged agent — browser={actual_browser}, headless={actual_headless}")

        placeholders = list(dict.fromkeys(
            re.findall(rf'\[{PLACEHOLDER_PREFIX}: ([^\]]+)\]', script_v1)
        ))

        if not placeholders:
            logger.info("No placeholders — executing script directly")
            exec_result = await self._execute_phase4(
                script_v1, app_url, actual_headless, actual_browser,
                on_step=on_step, test_case_id=test_case_id,
            )
            return self._result(
                script_v1, "completed",
                exec_result["steps_passed"], exec_result["steps_failed"],
                0, None, time.time() - start,
                exec_result["step_details"], exec_result.get("screenshot"),
                locator_mapping={},
            )

        actions = self._parse_ts_actions(script_v1, app_url)
        if not actions:
            return self._result(
                script_v1, "error", 0, 0, len(placeholders),
                "No parseable actions found in script",
                time.time() - start, locator_mapping={},
            )

        logger.info(f"Executing {len(actions)} actions with {len(placeholders)} placeholders to resolve")

        accumulated_mapping: Dict[str, str] = {}
        steps_passed = 0
        steps_failed = 0
        step_details: List[Dict[str, Any]] = []
        screenshot_b64: Optional[str] = None
        current_snapshot_text: Optional[str] = None
        llm = create_llm(temperature=LLM_TEMPERATURE, model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS)

        async with PlaywrightMCPClient(headless=actual_headless, browser=actual_browser) as mcp:
            tools = {t.name: t for t in mcp.tools}

            if not {"browser_navigate", "browser_snapshot"}.issubset(tools):
                return self._result(
                    script_v1, "error", 0, 0, len(placeholders),
                    "Required MCP tools not available",
                    time.time() - start, locator_mapping={},
                )

            for i, action in enumerate(actions):
                label = self._action_label(i + 1, action)
                success = False
                error_msg: Optional[str] = None

                try:
                    atype = action["type"]

                    if atype == "navigate":
                        await tools["browser_navigate"].ainvoke({"url": action["url"]})
                        # Pre-warm: wait for page to load and DOM to stabilise
                        current_snapshot_text = await self._wait_for_dom_stable(
                            tools, max_wait=10.0, check_interval=0.6, stable_checks=2
                        )
                        success = True

                    elif atype == "wait":
                        ms = action.get("ms", 1000)
                        if "browser_wait_for" in tools:
                            await tools["browser_wait_for"].ainvoke({"time": ms})
                        else:
                            await asyncio.sleep(ms / 1000)
                        success = True

                    elif atype == "press":
                        if "browser_press_key" not in tools:
                            raise RuntimeError("browser_press_key not available")
                        key = action.get("key", "Enter")
                        await tools["browser_press_key"].ainvoke({"key": key})
                        # Enter/Return may submit a form — treat like a click
                        if key.lower() in ("enter", "return"):
                            current_snapshot_text = await self._wait_for_dom_stable(
                                tools, max_wait=6.0, check_interval=0.5, stable_checks=2
                            )
                        else:
                            await asyncio.sleep(0.3)
                        success = True

                    else:
                        # Element action — resolve placeholder if present
                        locator = action.get("locator", "")
                        ph_match = re.search(rf'\[{PLACEHOLDER_PREFIX}: ([^\]]+)\]', locator)

                        if ph_match:
                            ph_desc = ph_match.group(1)

                            if ph_desc not in accumulated_mapping:
                                # Snapshot current page once (cache until navigation/failure)
                                if current_snapshot_text is None:
                                    raw = str(await tools["browser_snapshot"].ainvoke({}))
                                    current_snapshot_text = self._extract_snapshot_text(raw)

                                dom = _compress_dom(current_snapshot_text)

                                # Batch: collect all same-page unresolved placeholders
                                batch = [ph_desc]
                                for future_action in actions[i + 1:]:
                                    if future_action["type"] == "navigate":
                                        break  # different page — stop batching
                                    fut_loc = future_action.get("locator", "")
                                    if fut_loc:
                                        m = re.search(rf'\[{PLACEHOLDER_PREFIX}: ([^\]]+)\]', fut_loc)
                                        if m and m.group(1) not in accumulated_mapping and m.group(1) not in batch:
                                            batch.append(m.group(1))

                                logger.info(f"Resolving {len(batch)} placeholder(s) for current page state")
                                new_mapping = await self._resolve_placeholders(llm, batch, dom)
                                accumulated_mapping.update(new_mapping)

                            real_locator = accumulated_mapping.get(ph_desc)
                            if not real_locator:
                                raise RuntimeError(
                                    f"Could not resolve placeholder: [{PLACEHOLDER_PREFIX}: {ph_desc}]"
                                )
                            action = {**action, "locator": real_locator}

                        await self._execute_single_action(
                            tools, action, snapshot_text=current_snapshot_text
                        )

                        # Click may trigger navigation or dynamic DOM update →
                        # wait for DOM to stabilise and cache the result
                        if atype == "click":
                            current_snapshot_text = await self._wait_for_dom_stable(
                                tools, max_wait=6.0, check_interval=0.5, stable_checks=2
                            )

                        success = True

                except Exception as first_err:
                    logger.warning(f"Step {i + 1} failed ({first_err}) — self-correcting")
                    sc_desc: Optional[str] = None  # initialise so Tier 3 can access it
                    try:
                        current_snapshot_text = await self._wait_for_dom_stable(
                            tools, max_wait=4.0, check_interval=0.5, stable_checks=2
                        )
                        orig_locator = action.get("locator", "")

                        # Recover the placeholder description for this locator
                        reverse_map = {loc: desc for desc, loc in accumulated_mapping.items()}
                        sc_desc = reverse_map.get(orig_locator)
                        if not sc_desc:
                            m_ph = re.search(rf'\[{PLACEHOLDER_PREFIX}: ([^\]]+)\]', orig_locator)
                            if m_ph:
                                sc_desc = m_ph.group(1)

                        if sc_desc:
                            # Tier 1: LLM picks [ref=eXX] directly from raw DOM
                            direct_ref = await self._find_ref_via_llm(
                                llm, current_snapshot_text, sc_desc, action["type"]
                            )
                            if direct_ref:
                                action = {**action, "_ref": direct_ref}
                                logger.info(
                                    f"🤖 Tier1 direct ref: '{sc_desc[:50]}' → '{direct_ref}'"
                                )
                            else:
                                # Tier 2: corrected locator expression
                                dom = _compress_dom(current_snapshot_text)
                                corrected = await self._resolve_placeholders(llm, [sc_desc], dom)
                                new_locator = corrected.get(sc_desc)
                                if new_locator and new_locator != orig_locator:
                                    accumulated_mapping[sc_desc] = new_locator
                                    action = {**action, "locator": new_locator}
                                    logger.info(
                                        f"🤖 Tier2 locator: '{sc_desc[:40]}' → {new_locator[:50]}"
                                    )

                        await self._execute_single_action(
                            tools, action, snapshot_text=current_snapshot_text
                        )
                        success = True

                    except Exception as retry_err:
                        # Tier 3: LLM proposes a full multi-step recovery sequence.
                        # Handles overlays, animations, collapsed containers,
                        # custom dropdowns, off-screen elements — any complex UI.
                        recovered = False
                        if sc_desc:
                            try:
                                logger.info(
                                    f"🔧 Tier3 recovery for: '{sc_desc[:60]}'"
                                )
                                recovery_steps = await self._llm_recovery_sequence(
                                    llm,
                                    current_snapshot_text,
                                    description=sc_desc,
                                    action_type=action["type"],
                                    error_msg=str(retry_err),
                                )
                                if recovery_steps:
                                    ok = await self._execute_recovery_steps(tools, recovery_steps)
                                    if ok:
                                        # Re-stabilise DOM after recovery sequence
                                        current_snapshot_text = await self._wait_for_dom_stable(
                                            tools, max_wait=4.0, check_interval=0.5, stable_checks=2
                                        )
                                        # Final attempt: re-resolve the target ref on the new DOM
                                        final_ref = await self._find_ref_via_llm(
                                            llm, current_snapshot_text, sc_desc, action["type"]
                                        )
                                        final_action = (
                                            {**action, "_ref": final_ref} if final_ref
                                            else {k: v for k, v in action.items() if k != "_ref"}
                                        )
                                        await self._execute_single_action(
                                            tools, final_action,
                                            snapshot_text=current_snapshot_text,
                                        )
                                        recovered = True
                                        logger.info(f"🔧 Tier3 recovery succeeded for step {i + 1}")
                            except Exception as t3_err:
                                logger.warning(f"❌ Tier3 failed: {t3_err}")

                        if recovered:
                            success = True
                        else:
                            error_msg = str(retry_err)
                            logger.warning(f"❌ Step {i + 1} all tiers exhausted: {retry_err}")

                if success:
                    steps_passed += 1
                    step_details.append({"step": label, "status": "passed"})
                    logger.info(f"✅ {label}")
                    if on_step:
                        await on_step(label, "passed")
                else:
                    steps_failed += 1
                    step_details.append({"step": label, "status": "failed", "error": error_msg})
                    if on_step:
                        await on_step(label, "failed", error=error_msg)

            # Final screenshot
            if "browser_take_screenshot" in tools:
                try:
                    raw = await tools["browser_take_screenshot"].ainvoke({})
                    screenshot_b64 = self._extract_screenshot_b64(raw)
                    if screenshot_b64 and test_case_id:
                        import os, base64 as b64lib
                        screenshot_dir = "screenshots"
                        os.makedirs(screenshot_dir, exist_ok=True)
                        ts = time.strftime("%Y%m%d-%H%M%S")
                        fname = f"{screenshot_dir}/test_{test_case_id}_{ts}.png"
                        with open(fname, "wb") as f:
                            f.write(b64lib.b64decode(screenshot_b64))
                        logger.info(f"📸 Screenshot saved: {fname}")
                except Exception as e:
                    logger.warning(f"Screenshot failed: {e}")

        script_v2 = self._apply_mapping(script_v1, accumulated_mapping)
        remaining = len(re.findall(rf'\[{PLACEHOLDER_PREFIX}:', script_v2))
        status = "completed" if remaining == 0 else "partial"

        result = self._result(
            script_v2, status,
            steps_passed=steps_passed,
            steps_failed=steps_failed,
            remaining=remaining,
            error=None if remaining == 0 else f"{remaining} placeholder(s) could not be resolved",
            duration=time.time() - start,
            step_details=step_details,
            screenshot=screenshot_b64,
            locator_mapping=accumulated_mapping,
        )

        return result

    # ── DOM stability polling ────────────────────────────────────────────────────

    async def _wait_for_dom_stable(
        self,
        tools: dict,
        max_wait: float = 6.0,
        check_interval: float = 0.5,
        stable_checks: int = 2,
    ) -> str:
        """
        Poll browser_snapshot until the accessibility tree stops changing.
        Requires `stable_checks` consecutive identical snapshots before declaring
        the DOM stable. Falls back to the last seen snapshot after max_wait seconds.

        Returns the stable (or last seen) snapshot text, ready for use — avoids
        an extra snapshot call on the next step.
        """
        prev: Optional[str] = None
        consecutive = 0
        elapsed = 0.0

        while elapsed < max_wait:
            await asyncio.sleep(check_interval)
            raw = str(await tools["browser_snapshot"].ainvoke({}))
            current = self._extract_snapshot_text(raw)

            if current == prev:
                consecutive += 1
                if consecutive >= stable_checks:
                    logger.info(
                        f"DOM stable after {elapsed + check_interval:.1f}s "
                        f"({stable_checks} identical snapshots)"
                    )
                    return current
            else:
                consecutive = 0

            prev = current
            elapsed += check_interval

        logger.warning(f"DOM did not stabilize within {max_wait}s — using last snapshot")
        return prev or ""

    # ── Snapshot helper ──────────────────────────────────────────────────────────

    def _extract_snapshot_text(self, raw_snapshot: str) -> str:
        """
        Extract plain YAML text from an MCP browser_snapshot response.

        The MCP server can return the snapshot in several formats:
          1. JSON list of content blocks → join the "text" fields
          2. A string containing a ```yaml\\n...\\n``` code fence with escaped newlines
          3. A plain string (possibly with escaped newlines)

        In all cases we unescape literal \\n sequences so that splitlines() works
        correctly downstream — without this, every search runs on one giant string
        and always hits the outermost container ref first.
        """
        snapshot_text = raw_snapshot

        # Format 1: JSON list from langchain_mcp_adapters
        try:
            parsed = json.loads(raw_snapshot)
            if isinstance(parsed, list):
                texts = [item["text"] for item in parsed if isinstance(item, dict) and "text" in item]
                if texts:
                    snapshot_text = "\n".join(texts)
        except Exception:
            pass

        # Format 2: YAML inside ```yaml\n...\n``` code fences (escaped newlines)
        yaml_match = re.search(r'```yaml\\n(.*?)\\n```', snapshot_text, re.DOTALL)
        if yaml_match:
            snapshot_text = yaml_match.group(1)

        # Unescape literal \n sequences so splitlines() produces one element per node
        if '\\n' in snapshot_text:
            snapshot_text = snapshot_text.replace('\\n', '\n')

        return snapshot_text

    # ── Phase 4: execution (used when script has no placeholders) ────────────────

    async def _execute_phase4(
        self,
        script_v2: str,
        app_url: str,
        headless: bool,
        browser: str,
        timeout_seconds: int = 120,
        on_step=None,
        test_case_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Open a fresh browser session, parse script_v2 TypeScript, replay
        each action via MCP tools, and collect step-level pass/fail results.
        on_step: optional async callable(label, status, error=None) pushed per step.
        """
        actions = self._parse_ts_actions(script_v2, app_url)
        if not actions:
            logger.warning("Phase 4 — no parseable actions found in script_v2")
            return {"steps_passed": 0, "steps_failed": 0, "step_details": [], "screenshot": None}

        logger.info(f"Phase 4 — {len(actions)} actions to execute")

        steps_passed = 0
        steps_failed = 0
        step_details: List[Dict[str, Any]] = []
        screenshot_b64: Optional[str] = None

        async with PlaywrightMCPClient(
            timeout_seconds=timeout_seconds,
            headless=headless,
            browser=browser,
        ) as mcp:
            tools = {t.name: t for t in mcp.tools}
            logger.info(f"Phase 4 — available tools: {list(tools.keys())}")

            for i, action in enumerate(actions):
                label = self._action_label(i + 1, action)
                try:
                    await self._execute_single_action(tools, action)
                    steps_passed += 1
                    detail = {"step": label, "status": "passed"}
                    step_details.append(detail)
                    logger.info(f"✅ {label}")
                    if on_step:
                        await on_step(label, "passed")
                except Exception as e:
                    steps_failed += 1
                    detail = {"step": label, "status": "failed", "error": str(e)}
                    step_details.append(detail)
                    logger.warning(f"❌ {label}: {e}")
                    if on_step:
                        await on_step(label, "failed", error=str(e))
                    # Continue executing remaining steps even if one fails

            # Take final screenshot regardless of results
            if "browser_take_screenshot" in tools:
                try:
                    raw = await tools["browser_take_screenshot"].ainvoke({})
                    screenshot_b64 = self._extract_screenshot_b64(raw)
                    if screenshot_b64:
                        logger.info("Phase 4 — final screenshot captured")
                        
                        if test_case_id:
                            import os, base64
                            screenshot_dir = "screenshots"
                            os.makedirs(screenshot_dir, exist_ok=True)
                            timestamp = time.strftime("%Y%m%d-%H%M%S")
                            filename = f"{screenshot_dir}/test_{test_case_id}_{timestamp}.png"
                            with open(filename, "wb") as f:
                                f.write(base64.b64decode(screenshot_b64))
                            logger.info(f"📸 Screenshot saved locally: {filename}")
                except Exception as e:
                    logger.warning(f"Phase 4 — screenshot failed: {e}")

        logger.info(
            f"Phase 4 done — {steps_passed} passed, {steps_failed} failed "
            f"out of {len(actions)} steps"
        )
        return {
            "steps_passed": steps_passed,
            "steps_failed": steps_failed,
            "step_details": step_details,
            "screenshot": screenshot_b64,
        }

    # ── Shared-session variants (no MCP context manager — tools already open) ──────

    async def _execute_phase4_inner(
        self,
        tools: dict,
        script_v2: str,
        on_step=None,
        test_case_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a placeholder-free script using an already-open tools dict.
        Identical to _execute_phase4 but without opening PlaywrightMCPClient.
        """
        actions = self._parse_ts_actions(script_v2, "")
        if not actions:
            return {"steps_passed": 0, "steps_failed": 0, "step_details": [], "screenshot": None}

        steps_passed = steps_failed = 0
        step_details: List[Dict[str, Any]] = []
        screenshot_b64: Optional[str] = None

        for i, action in enumerate(actions):
            label = self._action_label(i + 1, action)
            try:
                await self._execute_single_action(tools, action)
                steps_passed += 1
                step_details.append({"step": label, "status": "passed"})
                logger.info(f"✅ {label}")
                if on_step:
                    await on_step(label, "passed")
            except Exception as e:
                steps_failed += 1
                step_details.append({"step": label, "status": "failed", "error": str(e)})
                logger.warning(f"❌ {label}: {e}")
                if on_step:
                    await on_step(label, "failed", error=str(e))

        if "browser_take_screenshot" in tools:
            try:
                raw = await tools["browser_take_screenshot"].ainvoke({})
                screenshot_b64 = self._extract_screenshot_b64(raw)
            except Exception:
                pass

        return {"steps_passed": steps_passed, "steps_failed": steps_failed,
                "step_details": step_details, "screenshot": screenshot_b64}

    async def run_with_tools(
        self,
        tools: dict,
        script_v1: str,
        app_url: str = APP_BASE_URL,
        test_case_id: Optional[str] = None,
        on_step=None,
    ) -> Dict[str, Any]:
        """
        Execute a script using an already-open MCP tools dict.
        Used by run_suite_smart for the shared-browser-session optimisation —
        the caller opens PlaywrightMCPClient once for the whole suite and passes
        the tools dict here so we never pay the browser launch cost per TC.
        """
        start = time.time()

        placeholders = list(dict.fromkeys(
            re.findall(rf'\[{PLACEHOLDER_PREFIX}: ([^\]]+)\]', script_v1)
        ))

        # No placeholders — straight execution
        if not placeholders:
            exec_result = await self._execute_phase4_inner(
                tools, script_v1, on_step=on_step, test_case_id=test_case_id,
            )
            return self._result(
                script_v1, "completed",
                exec_result["steps_passed"], exec_result["steps_failed"],
                0, None, time.time() - start,
                exec_result["step_details"], exec_result.get("screenshot"),
                locator_mapping={},
            )

        actions = self._parse_ts_actions(script_v1, app_url)
        if not actions:
            return self._result(
                script_v1, "error", 0, 0, len(placeholders),
                "No parseable actions found in script",
                time.time() - start, locator_mapping={},
            )

        if not {"browser_navigate", "browser_snapshot"}.issubset(tools):
            return self._result(
                script_v1, "error", 0, 0, len(placeholders),
                "Required MCP tools not available",
                time.time() - start, locator_mapping={},
            )

        accumulated_mapping: Dict[str, str] = {}
        steps_passed = steps_failed = 0
        step_details: List[Dict[str, Any]] = []
        screenshot_b64: Optional[str] = None
        current_snapshot_text: Optional[str] = None
        llm = create_llm(temperature=LLM_TEMPERATURE, model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS)

        for i, action in enumerate(actions):
            label = self._action_label(i + 1, action)
            success = False
            error_msg: Optional[str] = None

            try:
                atype = action["type"]

                if atype == "navigate":
                    await tools["browser_navigate"].ainvoke({"url": action["url"]})
                    current_snapshot_text = await self._wait_for_dom_stable(
                        tools, max_wait=10.0, check_interval=0.6, stable_checks=2
                    )
                    success = True

                elif atype == "wait":
                    ms = action.get("ms", 1000)
                    if "browser_wait_for" in tools:
                        await tools["browser_wait_for"].ainvoke({"time": ms})
                    else:
                        await asyncio.sleep(ms / 1000)
                    success = True

                elif atype == "press":
                    if "browser_press_key" not in tools:
                        raise RuntimeError("browser_press_key not available")
                    key = action.get("key", "Enter")
                    await tools["browser_press_key"].ainvoke({"key": key})
                    if key.lower() in ("enter", "return"):
                        current_snapshot_text = await self._wait_for_dom_stable(
                            tools, max_wait=6.0, check_interval=0.5, stable_checks=2
                        )
                    else:
                        await asyncio.sleep(0.3)
                    success = True

                else:
                    locator = action.get("locator", "")
                    ph_match = re.search(rf'\[{PLACEHOLDER_PREFIX}: ([^\]]+)\]', locator)

                    if ph_match:
                        ph_desc = ph_match.group(1)
                        if ph_desc not in accumulated_mapping:
                            if current_snapshot_text is None:
                                raw = str(await tools["browser_snapshot"].ainvoke({}))
                                current_snapshot_text = self._extract_snapshot_text(raw)
                            dom = _compress_dom(current_snapshot_text)
                            batch = [ph_desc]
                            for future_action in actions[i + 1:]:
                                if future_action["type"] == "navigate":
                                    break
                                fut_loc = future_action.get("locator", "")
                                if fut_loc:
                                    m = re.search(rf'\[{PLACEHOLDER_PREFIX}: ([^\]]+)\]', fut_loc)
                                    if m and m.group(1) not in accumulated_mapping and m.group(1) not in batch:
                                        batch.append(m.group(1))
                            new_mapping = await self._resolve_placeholders(llm, batch, dom)
                            accumulated_mapping.update(new_mapping)

                        real_locator = accumulated_mapping.get(ph_desc)
                        if not real_locator:
                            raise RuntimeError(f"Could not resolve placeholder: [{PLACEHOLDER_PREFIX}: {ph_desc}]")
                        action = {**action, "locator": real_locator}

                    await self._execute_single_action(tools, action, snapshot_text=current_snapshot_text)
                    if atype == "click":
                        current_snapshot_text = await self._wait_for_dom_stable(
                            tools, max_wait=6.0, check_interval=0.5, stable_checks=2
                        )
                    success = True

            except Exception as first_err:
                logger.warning(f"Step {i + 1} failed ({first_err}) — self-correcting")
                sc_desc: Optional[str] = None
                try:
                    current_snapshot_text = await self._wait_for_dom_stable(
                        tools, max_wait=4.0, check_interval=0.5, stable_checks=2
                    )
                    orig_locator = action.get("locator", "")
                    reverse_map = {loc: desc for desc, loc in accumulated_mapping.items()}
                    sc_desc = reverse_map.get(orig_locator)
                    if not sc_desc:
                        m_ph = re.search(rf'\[{PLACEHOLDER_PREFIX}: ([^\]]+)\]', orig_locator)
                        if m_ph:
                            sc_desc = m_ph.group(1)

                    if sc_desc:
                        direct_ref = await self._find_ref_via_llm(llm, current_snapshot_text, sc_desc, action["type"])
                        if direct_ref:
                            action = {**action, "_ref": direct_ref}
                        else:
                            dom = _compress_dom(current_snapshot_text)
                            corrected = await self._resolve_placeholders(llm, [sc_desc], dom)
                            new_locator = corrected.get(sc_desc)
                            if new_locator and new_locator != orig_locator:
                                accumulated_mapping[sc_desc] = new_locator
                                action = {**action, "locator": new_locator}

                    await self._execute_single_action(tools, action, snapshot_text=current_snapshot_text)
                    success = True

                except Exception as retry_err:
                    recovered = False
                    if sc_desc:
                        try:
                            recovery_steps = await self._llm_recovery_sequence(
                                llm, current_snapshot_text,
                                description=sc_desc, action_type=action["type"], error_msg=str(retry_err),
                            )
                            if recovery_steps:
                                ok = await self._execute_recovery_steps(tools, recovery_steps)
                                if ok:
                                    current_snapshot_text = await self._wait_for_dom_stable(
                                        tools, max_wait=4.0, check_interval=0.5, stable_checks=2
                                    )
                                    final_ref = await self._find_ref_via_llm(llm, current_snapshot_text, sc_desc, action["type"])
                                    final_action = (
                                        {**action, "_ref": final_ref} if final_ref
                                        else {k: v for k, v in action.items() if k != "_ref"}
                                    )
                                    await self._execute_single_action(tools, final_action, snapshot_text=current_snapshot_text)
                                    recovered = True
                        except Exception as t3_err:
                            logger.warning(f"❌ Tier3 failed: {t3_err}")

                    if recovered:
                        success = True
                    else:
                        error_msg = str(retry_err)

            if success:
                steps_passed += 1
                step_details.append({"step": label, "status": "passed"})
                logger.info(f"✅ {label}")
                if on_step:
                    await on_step(label, "passed")
            else:
                steps_failed += 1
                step_details.append({"step": label, "status": "failed", "error": error_msg})
                if on_step:
                    await on_step(label, "failed", error=error_msg)

        if "browser_take_screenshot" in tools:
            try:
                raw = await tools["browser_take_screenshot"].ainvoke({})
                screenshot_b64 = self._extract_screenshot_b64(raw)
            except Exception:
                pass

        script_v2 = self._apply_mapping(script_v1, accumulated_mapping)
        remaining = len(re.findall(rf'\[{PLACEHOLDER_PREFIX}:', script_v2))
        status = "completed" if remaining == 0 else "partial"

        return self._result(
            script_v2, status,
            steps_passed=steps_passed, steps_failed=steps_failed,
            remaining=remaining,
            error=None if remaining == 0 else f"{remaining} placeholder(s) could not be resolved",
            duration=time.time() - start,
            step_details=step_details, screenshot=screenshot_b64,
            locator_mapping=accumulated_mapping,
        )

    def _elem_params(self, tool, ref: str, description: str) -> dict:
        """
        Build the element-targeting params for an MCP tool call.

        Recent @playwright/mcp versions expose a `ref` field (the aria ref
        from the snapshot) alongside an `element` field (human description).
        Passing the aria ref in `ref` lets the server reuse our snapshot
        instead of re-snapshotting and potentially picking a different element.

        Older versions only have `element` or `target`, in which case we fall
        back to the description string.
        """
        try:
            if hasattr(tool, "args_schema") and tool.args_schema:
                props = tool.args_schema.schema().get("properties", {})
                logger.info(f"🔍 ELEM_PARAMS: tool properties={list(props.keys())}")
                if "ref" in props:
                    logger.info(f"🔍 ELEM_PARAMS: using ref={ref}")
                    desc_key = "target" if "target" in props else "element"
                    return {desc_key: description, "ref": ref}
                if "target" in props:
                    logger.info(f"🔍 ELEM_PARAMS: using target={ref} (no ref field)")
                    return {"target": ref}
        except Exception as e:
            logger.warning(f"🔍 ELEM_PARAMS error: {e}")
        return {"target": ref}

    

    async def _execute_single_action(
        self, tools: dict, action: dict, snapshot_text: Optional[str] = None
    ) -> None:
        """
        Dispatch one parsed action to the correct MCP tool.
        snapshot_text: if provided, use it for ref lookup without re-snapshotting.
        """
        atype = action["type"]

        if atype == "navigate":
            if "browser_navigate" not in tools:
                raise RuntimeError("browser_navigate not available")
            await tools["browser_navigate"].ainvoke({"url": action["url"]})
            await asyncio.sleep(1.5)
            return

        if atype == "wait":
            ms = action.get("ms", 1000)
            if "browser_wait_for" in tools:
                await tools["browser_wait_for"].ainvoke({"time": ms})
            else:
                await asyncio.sleep(ms / 1000)
            return

        if atype == "press":
            if "browser_press_key" not in tools:
                raise RuntimeError("browser_press_key not available")
            await tools["browser_press_key"].ainvoke({"key": action.get("key", "Enter")})
            await asyncio.sleep(1.0)
            return

        # Actions that need an element ref
        locator_expr = action.get("locator", "")

        # Skip assert_visible with unstable auto-generated IDs before attempting ref lookup
        if atype == "assert_visible" and self._is_unstable_locator(locator_expr):
            logger.warning(f"⚠️ Skipping assert_visible with unstable locator: {locator_expr[:80]}")
            return

        # LLM direct-ref injection: self-correction already identified the exact ref
        if "_ref" in action:
            ref = action["_ref"]
            logger.info(f"🔍 Using LLM-resolved ref='{ref}' for '{locator_expr[:60]}'")
        else:
            ref = None
            try:
                ref, _ = await self._resolve_ref(tools, locator_expr, snapshot_text=snapshot_text)
                logger.info(f"🔍 RESOLVE_REF: locator='{locator_expr[:60]}' → ref='{ref}'")
            except Exception as first_error:
                # assert_visible: wait briefly for dynamic elements (toasts, error messages)
                if atype == "assert_visible" and "browser_snapshot" in tools:
                    await asyncio.sleep(1.5)
                    fr = str(await tools["browser_snapshot"].ainvoke({}))
                    fs = self._extract_snapshot_text(fr)
                    ref = (
                        self._find_ref_in_snapshot(fs, locator_expr)
                        or self._find_ref_by_visible_text(fs, locator_expr)
                    )
                    if ref:
                        logger.info(f"🔍 RESOLVE_REF delayed: '{locator_expr[:60]}' → ref='{ref}'")

                if ref is None:
                    # Generic text fallback before giving up
                    try:
                        if "browser_snapshot" not in tools:
                            raise RuntimeError("browser_snapshot not available") from first_error
                        fresh_raw = str(await tools["browser_snapshot"].ainvoke({}))
                        fresh_snapshot = self._extract_snapshot_text(fresh_raw)
                        ref = self._find_ref_by_visible_text(fresh_snapshot, locator_expr)
                        if not ref:
                            raise RuntimeError(
                                f"Element not found: {locator_expr[:80]}"
                            ) from first_error
                    except RuntimeError:
                        raise
                    except Exception as fe:
                        raise RuntimeError(f"All attempts failed for: {locator_expr[:80]}") from fe

        if atype == "click":
            if "browser_click" not in tools:
                raise RuntimeError("browser_click not available")
            await tools["browser_click"].ainvoke(
                self._elem_params(tools["browser_click"], ref, locator_expr)
            )
            await asyncio.sleep(0.5)

        elif atype in ("fill", "type"):
            if "browser_type" not in tools:
                raise RuntimeError("browser_type not available")
            elem_params = self._elem_params(tools["browser_type"], ref, locator_expr)
            fill_params = {**elem_params, "text": action.get("value", "")}
            logger.info(f"🔍 FILL PARAMS SENT TO MCP: ref={ref} | params={json.dumps(fill_params)}")
            await tools["browser_type"].ainvoke(fill_params)
            await asyncio.sleep(0.3)

        elif atype == "select_option":
            if "browser_select_option" not in tools:
                raise RuntimeError("browser_select_option not available")
            await tools["browser_select_option"].ainvoke({
                **self._elem_params(tools["browser_select_option"], ref, locator_expr),
                "values": [action.get("value", "")],
            })
            await asyncio.sleep(0.3)

        elif atype == "assert_visible":
            # Element was found in snapshot → assertion passes
            logger.info(f"✅ Assert visible: {locator_expr[:60]}")

        elif atype == "assert_url":
            # Vérifie que l'URL contient le texte attendu
            if "browser_snapshot" in tools:
                snap = str(await tools["browser_snapshot"].ainvoke({}))
                expected = action.get("url", "")
                if expected not in snap:
                    raise RuntimeError(f"URL mismatch: expected '{expected}' not found in page")
            logger.info(f"✅ Assert URL: {action.get('url', '')[:60]}")


    async def _resolve_ref(
        self, tools: dict, locator_expr: str, snapshot_text: Optional[str] = None
    ):
        """
        Find the MCP aria ref for a locator expression.
        Uses snapshot_text if provided (avoids extra browser call); otherwise re-snapshots.
        """
        if snapshot_text is None:
            if "browser_snapshot" not in tools:
                raise RuntimeError("browser_snapshot not available")
            raw = str(await tools["browser_snapshot"].ainvoke({}))
            snapshot_text = self._extract_snapshot_text(raw)

        ref = self._find_ref_in_snapshot(snapshot_text, locator_expr)

        if not ref:
            compressed = _compress_dom(snapshot_text)
            logger.warning(
                f"Element not found for locator: {locator_expr[:120]}\n"
                f"Current DOM (compressed):\n{compressed[:1500]}"
            )
            raise RuntimeError(
                f"Element not found in snapshot for locator: {locator_expr[:80]}"
            )
        logger.info(f"🔍 RESOLVE_REF: locator='{locator_expr[:60]}' → ref='{ref}'")
        return ref, locator_expr

    async def _find_ref_via_llm(
        self,
        llm,
        snapshot_text: str,
        description: str,
        action_type: str,
    ) -> Optional[str]:
        """
        Universal fallback: ask the LLM to identify which [ref=eXX] in the
        current accessibility tree matches the description and action type.

        Only lines that carry a [ref=] are sent — keeps the prompt small.
        The LLM returns just the ref ID (e.g. 'e23') or 'null'.
        Works for any app, any element type, without hardcoded rules.
        """
        ref_lines = [l for l in snapshot_text.splitlines() if "[ref=" in l]
        if not ref_lines:
            logger.warning("_find_ref_via_llm: snapshot has no ref lines")
            return None

        dom_excerpt = "\n".join(ref_lines[:120])  # cap to avoid token overflow

        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(content=REF_RESOLVER_SYSTEM),
                    HumanMessage(content=REF_RESOLVER_USER.format(
                        dom=dom_excerpt,
                        description=description,
                        action_type=action_type,
                    )),
                ],
            )
        except Exception as e:
            logger.warning(f"🤖 _find_ref_via_llm LLM call failed: {e}")
            return None

        result = response.content.strip()
        logger.info(f"🤖 _find_ref_via_llm raw: '{result[:80]}'")

        if result.lower() in ("null", "none", ""):
            return None

        # Model should return bare "e23" — validate it exists in the snapshot
        candidate = result.strip()
        if f"[ref={candidate}]" in snapshot_text:
            return candidate

        # Model sometimes returns "ref=e23" or "[ref=e23]" — extract the ID
        m = re.search(r"ref=([^\]\s,]+)", result, re.IGNORECASE)
        if m:
            candidate = m.group(1).rstrip("]")
            if f"[ref={candidate}]" in snapshot_text:
                return candidate

        # Last resort: pull first eNN token
        m = re.search(r"\b(e\d+)\b", result)
        if m:
            candidate = m.group(1)
            if f"[ref={candidate}]" in snapshot_text:
                return candidate

        logger.warning(f"🤖 _find_ref_via_llm: '{result[:80]}' not found in snapshot")
        return None

    async def _llm_recovery_sequence(
        self,
        llm,
        snapshot_text: str,
        description: str,
        action_type: str,
        error_msg: str,
    ) -> List[Dict[str, Any]]:
        """
        Tier-3 recovery: the LLM sees the current DOM and proposes a multi-step
        sequence to unblock the failing action.

        Covers: modal/overlay dismissal, collapsed accordions, closed dropdowns,
        animations, elements off-screen, autocomplete, date pickers, custom components.

        Returns a validated list of sub-action dicts, or [] if the element
        genuinely doesn't exist on this page.
        """
        ref_lines = [l for l in snapshot_text.splitlines() if "[ref=" in l]
        if not ref_lines:
            return []

        dom_refs = "\n".join(ref_lines[:150])

        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(content=RECOVERY_SYSTEM),
                    HumanMessage(content=RECOVERY_USER.format(
                        action_type=action_type,
                        description=description,
                        error=error_msg[:200],
                        dom_refs=dom_refs,
                    )),
                ],
            )
        except Exception as e:
            logger.warning(f"🔧 Recovery LLM call failed: {e}")
            return []

        content = response.content.strip()
        logger.info(f"🔧 Recovery sequence raw: {content[:400]}")

        m = re.search(r"\[.*\]", content, re.DOTALL)
        if not m:
            return []

        try:
            steps = json.loads(m.group(0))
        except json.JSONDecodeError:
            logger.warning(f"🔧 Recovery JSON parse failed: {content[:200]}")
            return []

        if not isinstance(steps, list):
            return []

        # Validate every ref-bearing step against the live snapshot
        valid: List[Dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            ref = step.get("ref")
            if ref and f"[ref={ref}]" not in snapshot_text:
                logger.warning(f"🔧 Recovery ref '{ref}' not in snapshot — dropping step")
                continue
            valid.append(step)

        logger.info(f"🔧 Recovery: {len(valid)} valid step(s) from LLM")
        return valid

    async def _execute_recovery_steps(
        self,
        tools: dict,
        steps: List[Dict[str, Any]],
    ) -> bool:
        """
        Execute the sub-action list returned by _llm_recovery_sequence.
        Returns True only if every step succeeded.
        """
        for step in steps:
            action = step.get("action", "")
            ref = step.get("ref", "")
            description = step.get("description", ref)

            try:
                if action == "wait":
                    await asyncio.sleep(step.get("ms", 500) / 1000)

                elif action == "press":
                    if "browser_press_key" in tools:
                        await tools["browser_press_key"].ainvoke(
                            {"key": step.get("key", "Escape")}
                        )
                        await asyncio.sleep(0.3)

                elif action == "scroll":
                    if "browser_scroll" in tools and ref:
                        await tools["browser_scroll"].ainvoke(
                            self._elem_params(tools["browser_scroll"], ref, description)
                        )
                        await asyncio.sleep(0.3)
                    # Graceful degradation: if tool absent, skip but don't fail

                elif action == "click":
                    if "browser_click" not in tools:
                        logger.warning("🔧 browser_click not available for recovery step")
                        return False
                    await tools["browser_click"].ainvoke(
                        self._elem_params(tools["browser_click"], ref, description)
                    )
                    await asyncio.sleep(0.5)

                elif action == "fill":
                    if "browser_type" not in tools:
                        logger.warning("🔧 browser_type not available for recovery step")
                        return False
                    params = self._elem_params(tools["browser_type"], ref, description)
                    await tools["browser_type"].ainvoke(
                        {**params, "text": step.get("value", "")}
                    )
                    await asyncio.sleep(0.3)

                else:
                    logger.warning(f"🔧 Unknown recovery action '{action}' — skipping")

                logger.info(f"🔧 Recovery step OK: {action} {ref or step.get('key', '')}")

            except Exception as e:
                logger.warning(f"🔧 Recovery step failed ({action} {ref}): {e}")
                return False

        return True

    # ── TypeScript script parser ─────────────────────────────────────────────────

    def _parse_ts_actions(self, script: str, app_url: str) -> List[Dict[str, Any]]:
        """
        Parse TypeScript Playwright script lines into a flat list of MCP-executable actions.
        Handles: goto, waitForTimeout, click, fill, type, press, selectOption, expect.toBeVisible.
        """
        actions: List[Dict[str, Any]] = []

        for line in script.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("import"):
                continue
            # Skip test() wrapper lines and closing braces
            if re.match(r"^(test|describe)\s*\(", stripped) or stripped in ("});", "}):", "{"):
                continue

            # page.goto(url)
            m = re.search(r"page\.goto\(['\"]([^'\"]+)['\"]\)", stripped)
            if m:
                url = m.group(1)
                if url.startswith("/"):
                    url = app_url.rstrip("/") + url
                actions.append({"type": "navigate", "url": url})
                continue

            # page.waitForTimeout(ms)
            m = re.search(r"page\.waitForTimeout\((\d+)\)", stripped)
            if m:
                actions.append({"type": "wait", "ms": int(m.group(1))})
                continue

            # .click()
            if ".click()" in stripped and "page." in stripped:
                locator = self._locator_before(stripped, ".click()")
                if locator:
                    actions.append({"type": "click", "locator": locator})
                    continue

            # .fill('value')  or  .fill("value")
            m = re.search(r"\.fill\(['\"]([^'\"]*)['\"]", stripped)
            if m and "page." in stripped:
                locator = self._locator_before(stripped, ".fill(")
                if locator:
                    actions.append({"type": "fill", "locator": locator, "value": m.group(1)})
                    continue

            # .type('value')
            m = re.search(r"\.type\(['\"]([^'\"]*)['\"]", stripped)
            if m and "page." in stripped:
                locator = self._locator_before(stripped, ".type(")
                if locator:
                    actions.append({"type": "type", "locator": locator, "value": m.group(1)})
                    continue

            # .press('key')
            m = re.search(r"\.press\(['\"]([^'\"]*)['\"]", stripped)
            if m and "page." in stripped:
                actions.append({"type": "press", "key": m.group(1)})
                continue

            # .selectOption('value')
            m = re.search(r"\.selectOption\(['\"]([^'\"]*)['\"]", stripped)
            if m and "page." in stripped:
                locator = self._locator_before(stripped, ".selectOption(")
                if locator:
                    actions.append({"type": "select_option", "locator": locator, "value": m.group(1)})
                    continue

            # expect(...).toBeVisible() — locator must be a Playwright expression
            m = re.search(r"expect\((.+)\)\.toBeVisible\(\)", stripped)
            if m:
                locator_expr = m.group(1).strip()
                # Accept if it contains a Playwright locator method or starts with page.
                if "page." in locator_expr or re.search(r"getBy\w+|\.locator\(", locator_expr):
                    actions.append({"type": "assert_visible", "locator": locator_expr})
                    continue

            # waitForSelector → transforme en assert_visible
            m = re.search(r"waitForSelector\(\"\[TESTFORGEAI:\s*([^\]]+)\]\"", stripped)
            if m:
                actions.append({"type": "assert_visible", "locator": f"page.locator(\"[TESTFORGEAI: {m.group(1)}]\")"})
                continue
            
            # toContain('...') → transforme en assert_url
            m = re.search(r"toContain\(['\"]([^'\"]+)['\"]\)", stripped)
            if m:
                actions.append({"type": "assert_url", "url": m.group(1)})
                continue

            # expect(...).toContainText / toHaveText — treat as assert_visible
            m = re.search(r"expect\((.+?)\)\.(toContainText|toHaveText|toBeEnabled|toBeChecked)\(", stripped)
            if m:
                locator_expr = m.group(1).strip()
                if "page." in locator_expr or re.search(r"getBy\w+|\.locator\(", locator_expr):
                    actions.append({"type": "assert_visible", "locator": locator_expr})
                    continue

            # expect(page).toHaveURL('...')
            m = re.search(r"expect\(page\)\.toHaveURL\(['\"]([^'\"]+)['\"]\)", stripped)
            if m:
                actions.append({"type": "assert_url", "url": m.group(1)})
                continue

        return actions

    def _locator_before(self, line: str, action_token: str) -> Optional[str]:
        """Extract the Playwright locator expression that precedes an action token."""
        idx = line.find(action_token)
        if idx < 0:
            return None
        # Slice from 'page.' to the action token
        part = line[:idx].strip()
        # Remove leading 'await '
        part = re.sub(r"^await\s+", "", part).strip()
        # Must start with page. to be a valid locator
        if not part.startswith("page."):
            return None
        return part

    # ── Snapshot ref resolution ──────────────────────────────────────────────────

    def _find_ref_in_snapshot(self, snapshot: str, locator_expr: str) -> Optional[str]:
        """
        Parse a TypeScript Playwright locator expression and find the matching
        element ref in the MCP accessibility-tree snapshot.
        """
        if not locator_expr or not snapshot:
            return None

        # getByRole('role', { name: 'text' })  or  getByRole("role")
        m = re.search(
            r"getByRole\(['\"](\w+)['\"](?:[^)]*?name\s*:\s*['\"]([^'\"]+)['\"])?",
            locator_expr,
        )
        if m:
            return self._snapshot_search(snapshot, role=m.group(1), name=m.group(2) or "")

        # getByLabel('text')  — no closing paren required so extra args are tolerated
        m = re.search(r"getByLabel\(['\"]([^'\"]+)['\"]", locator_expr)
        if m:
            return self._snapshot_search(snapshot, label=m.group(1))

        # getByText('text')  — same: tolerate { exact: false } and other extra args
        m = re.search(r"getByText\(['\"]([^'\"]+)['\"]", locator_expr)
        if m:
            return self._snapshot_search(snapshot, text=m.group(1))

        # getByTestId('id')
        m = re.search(r"getByTestId\(['\"]([^'\"]+)['\"]", locator_expr)
        if m:
            return self._snapshot_search(snapshot, testid=m.group(1))

        # getByPlaceholder('text')
        m = re.search(r"getByPlaceholder\(['\"]([^'\"]+)['\"]", locator_expr)
        if m:
            return self._snapshot_search(snapshot, placeholder=m.group(1))

        # locator('selector')
        m = re.search(r"locator\(['\"]([^'\"]+)['\"]\)", locator_expr)
        if m:
            return self._snapshot_search(snapshot, selector=m.group(1))

        return None

    def _find_ref_by_visible_text(self, snapshot: str, locator_expr: str) -> Optional[str]:
        """
        Fallback : cherche un élément uniquement par le texte visible qu'il contient.
        Ignore complètement le type de locator d'origine.
        
        Exemples :
            page.getByLabel('Email:')     → cherche "Email:"
            page.getByRole('button',...)  → cherche le nom du bouton
            page.locator('#email')        → cherche "email"
        """
        # Extrait le premier texte entre guillemets dans l'expression
        # getByLabel('Email:')      → Email:
        # getByRole('button', { name: 'Login' }) → Login
        # getByText('Welcome')      → Welcome
        
        # Cherche d'abord un name: '...'
        m = re.search(r"name\s*:\s*['\"]([^'\"]+)['\"]", locator_expr)
        if m:
            search_text = m.group(1).lower()
        else:
            # Sinon, prend le premier texte entre guillemets simples
            m = re.search(r"\('([^']+)'\)", locator_expr)
            if m:
                search_text = m.group(1).lower()
            else:
                # Ou guillemets doubles
                m = re.search(r'\"([^\"]+)\"\)', locator_expr)
                if m:
                    search_text = m.group(1).lower()
                else:
                    return None
        
        logger.info(f"Fallback: searching for text '{search_text}' in snapshot...")

        best_ref = None

        for line in snapshot.splitlines():
            ref_match = re.search(r"\[ref=([^\]]+)\]", line)
            if not ref_match:
                continue
            
            ref = ref_match.group(1)
            
            if search_text in line.lower():
                # Priorité maximale aux éléments interactifs
                if any(t in line for t in ["textbox", "button", "input", "select"]):
                    return ref
                # Garde le premier match générique en mémoire
                if best_ref is None:
                    best_ref = ref
    
        return best_ref
    
    # Container roles in the MCP accessibility tree — never use these as a fallback ref
    # because they resolve to wrapper divs/sections, not the actual target element.
    _CONTAINER_ROLES = frozenset([
        "generic", "region", "group", "section", "article", "main",
        "navigation", "banner", "complementary", "none", "presentation",
        "list", "listitem", "row", "grid", "table", "cell", "rowgroup",
        "separator", "toolbar", "tablist", "tabpanel", "tree", "treeitem",
    ])

    @staticmethod
    def _norm(text: str) -> str:
        """
        Normalise a label/name for fuzzy matching.
        Strips trailing punctuation and whitespace, lowercases.
        "Email:"  → "email"
        "Password *" → "password"
        """
        return re.sub(r'[\s:*]+$', '', text.lower().strip())

    def _snapshot_search(
        self,
        snapshot: str,
        role: str = "",
        name: str = "",
        label: str = "",
        text: str = "",
        testid: str = "",
        placeholder: str = "",
        selector: str = "",
    ) -> Optional[str]:
        """
        Scan MCP snapshot lines for an element matching the given criteria.

        Matching is fuzzy for name/label/text: both the raw and normalised forms
        (trailing colons/asterisks stripped) are tried, so "Email:" matches "email".

        Priority:
          1. Interactive element (textbox, button, …) → return immediately
          2. Non-container element → keep as best_ref, keep scanning
          3. Container elements (generic, region, …) blocked only for role= searches
        """
        best_ref = None

        # Pre-compute normalised forms once
        name_n        = self._norm(name)        if name        else ""
        label_n       = self._norm(label)       if label       else ""
        text_n        = self._norm(text)        if text        else ""
        placeholder_n = self._norm(placeholder) if placeholder else ""

        logger.info(
            f"🔍 SNAPSHOT_SEARCH role='{role}' name='{name}'({name_n}) "
            f"label='{label}'({label_n}) text='{text}'({text_n})"
        )

        for line in snapshot.splitlines():
            m = re.search(r"\[ref=([^\]]+)\]", line)
            if not m:
                continue
            ref = m.group(1)
            ll  = line.lower()

            is_interactive = any(
                t in ll for t in [
                    "textbox", "button", "input", "select",
                    "textarea", "checkbox", "radio", "combobox",
                    "link", "option", "menuitem", "spinbutton",
                ]
            )
            is_container = any(ck in ll for ck in self._CONTAINER_ROLES)

            def matches() -> bool:
                if role and name:
                    # Accept if role matches AND either raw or normalised name matches
                    return role.lower() in ll and (name.lower() in ll or name_n in ll)
                if role:
                    return role.lower() in ll
                if label:
                    return label.lower() in ll or label_n in ll
                if text:
                    return text.lower() in ll or text_n in ll
                if testid:
                    return testid.lower() in ll
                if placeholder:
                    return placeholder.lower() in ll or placeholder_n in ll
                if selector:
                    words = re.sub(r"[#.\[\]='\"{}>~+*^$|():]", " ", selector).split()
                    return any(len(w) > 2 and w.lower() in ll for w in words)
                return False

            if not matches():
                continue
            if line.count("[ref=") > 1:
                continue  # parent line inlining children refs — skip

            if is_interactive:
                logger.info(f"🔍 MATCH interactive ref={ref} → {line.strip()[:70]}")
                return ref

            # Block containers only when we expect an interactive element (role= set)
            if role and is_container:
                continue

            if best_ref is None:
                best_ref = ref

        logger.info(f"🔍 SNAPSHOT_SEARCH best_ref={best_ref}")
        return best_ref

    # ── helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _is_unstable_locator(locator_expr: str) -> bool:
        """
        Return True if the locator uses an auto-generated CSS ID that changes on
        every page load (UUIDs, long hex/alphanumeric hashes, framework-generated ids).
        These locators always fail and should be skipped rather than counted as failures.
        Examples:
            page.locator('#lc_a5785abd-9a5b-4bde-97f5-4f4c45b92637')  → True
            page.locator('#el-3f2a9b')                                  → True
            page.locator('#submit')                                     → False
            page.locator('#email')                                      → False
        """
        m = re.search(r"locator\(['\"]#([^'\"]+)['\"]", locator_expr)
        if not m:
            return False
        id_value = m.group(1)
        # UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
        if re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", id_value):
            return True
        # Generic hash: 16+ hex chars or underscore-separated UUID fragment
        if re.search(r"[0-9a-f]{16,}", id_value):
            return True
        # Long alphanumeric (20+ chars) with digits — framework-generated
        if len(id_value) >= 20 and re.search(r"\d", id_value) and re.search(r"[a-z]", id_value):
            return True
        return False

    async def _resolve_placeholders(self, llm, placeholders: list, dom: str) -> dict:
        """Single LLM call: compressed DOM + placeholder list → JSON locator mapping."""
        response = await llm.ainvoke(
            [
                SystemMessage(content=MAPPING_SYSTEM),
                HumanMessage(content=MAPPING_USER.format(
                    dom=dom,
                    placeholders=json.dumps(placeholders, indent=2),
                )),
            ],
        )

        content = response.content.strip()

        # Strip markdown code fences if the model wrapped the JSON
        match = re.search(r"\{.*\}", content, re.DOTALL)
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

    def _action_label(self, idx: int, action: dict) -> str:
        atype = action["type"]
        if atype == "navigate":
            return f"Step {idx}: navigate → {action.get('url', '')}"
        if atype == "wait":
            return f"Step {idx}: wait {action.get('ms', 0)}ms"
        if atype == "press":
            return f"Step {idx}: press {action.get('key', '')}"
        locator = action.get("locator", "")[:60]
        value = action.get("value", "")
        if atype == "click":
            return f"Step {idx}: click {locator}"
        if atype in ("fill", "type"):
            return f"Step {idx}: fill {locator} = '{value}'"
        if atype == "select_option":
            return f"Step {idx}: select '{value}' in {locator}"
        if atype == "assert_visible":
            return f"Step {idx}: assert visible {locator}"
        return f"Step {idx}: {atype}"

    def _extract_screenshot_b64(self, raw) -> Optional[str]:
        """Extract base64 data from an MCP browser_take_screenshot result."""
        logger.info(f"📸 Screenshot raw: type={type(raw).__name__}, preview={repr(raw)[:300]}")
    
        if isinstance(raw, list):
            for item in raw:
                # ContentBlock objects from langchain_mcp_adapters
                if hasattr(item, "type") and getattr(item, "type") == "image":
                    data = getattr(item, "data", None)
                    if data:
                        logger.info(f"📸 Extracted from ContentBlock, len={len(str(data))}")
                        return str(data)
                
                if isinstance(item, dict):
                    if item.get("type") == "image":
                        data = item.get("data")
                        if data:
                            logger.info(f"📸 Extracted from list[dict type=image], len={len(str(data))}")
                            return str(data)
                    if "data" in item and item["data"]:
                        logger.info("📸 Extracted from list[dict data]")
                        return str(item["data"])
                    # Cherche un chemin de fichier PNG dans le texte
                    if item.get("type") == "text":
                        text = item.get("text", "")
                        path_match = re.search(r'\(\.?([\w\-\/\\]+\.png)\)', text)
                        if path_match:
                            filepath = path_match.group(1)
                            import os, base64
                            if not os.path.isabs(filepath):
                                filepath = os.path.join(os.getcwd(), filepath)
                            try:
                                with open(filepath, 'rb') as f:
                                    b64 = base64.b64encode(f.read()).decode()
                                    logger.info(f"📸 Loaded screenshot from file: {filepath} ({len(b64)} chars)")
                                    return b64
                            except Exception as e:
                                logger.warning(f"📸 Failed to read screenshot file {filepath}: {e}")
    
        if isinstance(raw, dict):
            if raw.get("type") == "image":
                data = raw.get("data")
                if data:
                    return str(data)
            for key in ("data", "base64", "image"):
                if raw.get(key):
                    return str(raw[key])
    
        if isinstance(raw, str):
            if raw.startswith("data:image"):
                logger.info("📸 Extracted from data URI string")
                return raw.split(",", 1)[1] if "," in raw else None
            if len(raw) > 500 and " " not in raw.strip():
                logger.info(f"📸 Using raw string as base64, len={len(raw)}")
                return raw
    
        logger.warning(f"📸 Cannot extract screenshot — unrecognized format: {type(raw).__name__}")
        return None



    def _result(
        self,
        script_v2: str,
        status: str,
        steps_passed: int,
        steps_failed: int,
        remaining: int,
        error: Optional[str],
        duration: float,
        step_details: Optional[List[Dict[str, Any]]] = None,
        screenshot: Optional[str] = None,
        locator_mapping: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return {
            "script_v2": script_v2,
            "execution_status": status,
            "steps_passed": steps_passed,
            "steps_failed": steps_failed,
            "remaining_placeholders": remaining,
            "error": error,
            "duration": duration,
            "step_details": step_details or [],
            "screenshot": screenshot,
            "locator_mapping": locator_mapping or {},
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
