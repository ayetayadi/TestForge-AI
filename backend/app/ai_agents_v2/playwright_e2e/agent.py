import asyncio
import json
import logging
import re
import time
from typing import Dict, Any, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langfuse import observe
from langfuse import get_client as get_langfuse_client

from app.core.observability import fire_evaluation, get_trace_callback
from app.llm.llm_control import create_llm
from .tools import PlaywrightMCPClient
from .prompts import MAPPING_SYSTEM, MAPPING_USER
from .config import LLM_MAX_TOKENS, LLM_MODEL, LLM_TEMPERATURE, APP_BASE_URL, PLACEHOLDER_PREFIX

logger = logging.getLogger(__name__)

# Keyword filter for DOM compression — keeps only lines the LLM needs
_DOM_KEYWORDS = (
    "button", "input", "label", "link", "heading",
    "aria", "role", "select", "textarea", "checkbox", "radio",
    "placeholder", "name=", "value=", "textbox",
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
    Four-phase Playwright agent.

    Phase 1 — browser work:
        Navigate → ONE snapshot → get DOM

    Phase 2 — 1 LLM call:
        LLM maps ALL placeholders to real TypeScript locators

    Phase 3 — pure Python:
        Apply mapping to script_v1 → script_v2  (zero LLM calls)

    Phase 4 — browser execution:
        Parse script_v2 → replay actions via MCP tools → collect results
    """

    @observe(name="playwright_two_phase_agent")
    async def run(
        self,
        script_v1: str,
        app_url: str = APP_BASE_URL,
        test_case_id: Optional[str] = None,
        headless: Optional[bool] = None,
        browser: Optional[str] = None,
        on_step=None,  # optional async callable(label, status, error=None) for real-time SSE
    ) -> Dict[str, Any]:
        start = time.time()
        actual_headless = headless if headless is not None else True
        actual_browser = browser if browser is not None else "chromium"

        get_langfuse_client().update_current_span(
            input={"script_v1": script_v1, "app_url": app_url, "test_case_id": test_case_id},
            metadata={"browser": actual_browser, "headless": actual_headless},
        )

        logger.info(f"Four-phase agent — browser={actual_browser}, headless={actual_headless}")
        logger.info(f"App URL: {app_url}")

        # Extract unique placeholders, preserving order
        placeholders = list(dict.fromkeys(
            re.findall(rf'\[{PLACEHOLDER_PREFIX}: ([^\]]+)\]', script_v1)
        ))

        if not placeholders:
            logger.info("No placeholders found — skipping to Phase 4 with raw script")
            exec_result = await self._execute_phase4(script_v1, app_url, actual_headless, actual_browser, on_step=on_step)
            return self._result(
                script_v1, "completed",
                exec_result["steps_passed"], exec_result["steps_failed"],
                0, None, time.time() - start,
                exec_result["step_details"], exec_result.get("screenshot"),
            )

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
                logger.info("Phase 1 — Navigating to app...")
                await tools["browser_navigate"].ainvoke({"url": app_url})

                logger.info("Phase 1 — Taking DOM snapshot...")
                raw_snapshot = str(await tools["browser_snapshot"].ainvoke({}))
                # Extraire YAML
                snapshot_text = raw_snapshot
                try:
                    parsed = json.loads(raw_snapshot)
                    if isinstance(parsed, list):
                        texts = [item['text'] for item in parsed if isinstance(item, dict) and 'text' in item]
                        if texts:
                            snapshot_text = '\n'.join(texts)
                except Exception:
                    pass
                dom = _compress_dom(snapshot_text)
                logger.info(f"DOM compressed: {len(raw_snapshot)} → {len(dom)} chars")

            except Exception as e:
                logger.error(f"Browser phase failed: {e}", exc_info=True)
                return self._result(script_v1, "error", 0, 0, len(placeholders), str(e), time.time() - start)

        # ── Phase 2: ONE LLM call — map all placeholders ────────────────────────
        try:
            logger.info("Phase 2 — LLM mapping placeholders...")
            llm = create_llm(temperature=LLM_TEMPERATURE, model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS)
            mapping = await self._resolve_placeholders(llm, placeholders, dom)
            logger.info(f"Mapping resolved: {len(mapping)}/{len(placeholders)} placeholders")
        except Exception as e:
            logger.error(f"LLM mapping failed: {e}", exc_info=True)
            return self._result(script_v1, "error", 0, 0, len(placeholders), str(e), time.time() - start)

        # ── Phase 3: apply mapping — pure Python, zero LLM calls ────────────────
        logger.info("Phase 3 — Applying locator mapping...")
        script_v2 = self._apply_mapping(script_v1, mapping)
        remaining = len(re.findall(rf'\[{PLACEHOLDER_PREFIX}:', script_v2))
        resolved = len(placeholders) - remaining
        status = "completed" if remaining == 0 else "partial"

        logger.info(f"Phase 3 done — {resolved}/{len(placeholders)} resolved, status={status}")

        # ── Phase 4: execute actions from script_v2 in the browser ──────────────
        logger.info("Phase 4 — Executing test actions in browser...")
        try:
            exec_result = await self._execute_phase4(script_v2, app_url, actual_headless, actual_browser, on_step=on_step)
        except Exception as e:
            logger.error(f"Phase 4 execution failed: {e}", exc_info=True)
            exec_result = {"steps_passed": 0, "steps_failed": resolved, "step_details": [], "screenshot": None}

        result = self._result(
            script_v2, status,
            steps_passed=exec_result["steps_passed"],
            steps_failed=exec_result["steps_failed"],
            remaining=remaining,
            error=None if remaining == 0 else f"{remaining} placeholder(s) could not be resolved",
            duration=time.time() - start,
            step_details=exec_result["step_details"],
            screenshot=exec_result.get("screenshot"),
        )

        lf = get_langfuse_client()
        lf.update_current_span(
            output={
                "execution_status": result["execution_status"],
                "steps_passed": result["steps_passed"],
                "steps_failed": result["steps_failed"],
                "remaining_placeholders": result["remaining_placeholders"],
                "duration": round(result["duration"], 2),
            },
            metadata={"test_case_id": test_case_id, "total_placeholders": len(placeholders)},
        )

        if result["execution_status"] in ("completed", "partial"):
            trace_id = lf.get_current_trace_id()
            asyncio.create_task(fire_evaluation(
                metric="playwright_script_quality",
                input_text=script_v1,
                output_text=result["script_v2"],
                trace_id=trace_id,
            ))

        return result

    # ── Phase 4: execution ───────────────────────────────────────────────────────

    async def _execute_phase4(
        self,
        script_v2: str,
        app_url: str,
        headless: bool,
        browser: str,
        timeout_seconds: int = 120,
        on_step=None,
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
                        
                        # Sauvegarder localement
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

    

    async def _execute_single_action(self, tools: dict, action: dict) -> None:
        """Dispatch one parsed action to the correct MCP tool."""
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
        
        # ESSAI 1 : résolution normale
        try:
            ref, element_desc = await self._resolve_ref(tools, locator_expr)
            logger.info(f"🔍 RESOLVE_REF: locator='{locator_expr[:60]}' → ref='{ref}'")
        except Exception as first_error:
            # ESSAI 2 : fallback — cherche par texte visible dans la page
            logger.warning(
                f"First locator attempt failed: {locator_expr[:80]}. "
                f"Trying fallback by visible text..."
            )
            try:
                if "browser_snapshot" not in tools:
                    raise RuntimeError("browser_snapshot not available for fallback")
                snapshot_raw = str(await tools["browser_snapshot"].ainvoke({}))
                
                # Extraire le YAML directement avec regex
                yaml_match = re.search(r'```yaml\\n(.*?)\\n```', snapshot_raw, re.DOTALL)
                if yaml_match:
                    snapshot_text = yaml_match.group(1)
                    snapshot_text = snapshot_text.replace('\\n', '\n')
                    logger.info(f"🔍 YAML extracted via regex, {len(snapshot_text)} chars")
                else:
                    snapshot_text = snapshot_raw
                    logger.warning("🔍 No YAML block found, using raw snapshot")
                
                ref = self._find_ref_by_visible_text(snapshot_text, locator_expr)
                if not ref:
                    raise RuntimeError(
                        f"Fallback also failed for: {locator_expr[:80]}"
                    ) from first_error
            except Exception as fallback_error:
                raise RuntimeError(
                    f"All attempts failed for: {locator_expr[:80]}"
                ) from fallback_error

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
            # L'élément a été trouvé dans le snapshot → il existe
            logger.info(f"✅ Assert visible: {locator_expr[:60]}")

        elif atype == "assert_url":
            # Vérifie que l'URL contient le texte attendu
            if "browser_snapshot" in tools:
                snap = str(await tools["browser_snapshot"].ainvoke({}))
                expected = action.get("url", "")
                if expected not in snap:
                    raise RuntimeError(f"URL mismatch: expected '{expected}' not found in page")
            logger.info(f"✅ Assert URL: {action.get('url', '')[:60]}")


    async def _resolve_ref(self, tools: dict, locator_expr: str):
        if "browser_snapshot" not in tools:
            raise RuntimeError("browser_snapshot not available")
    
        snapshot_raw = str(await tools["browser_snapshot"].ainvoke({}))
    
        # Extraire le YAML directement avec regex
        yaml_match = re.search(r'```yaml\\n(.*?)\\n```', snapshot_raw, re.DOTALL)
        if yaml_match:
            snapshot_text = yaml_match.group(1)
            snapshot_text = snapshot_text.replace('\\n', '\n')
            logger.info(f"🔍 YAML extracted via regex, {len(snapshot_text)} chars")
        else:
            snapshot_text = snapshot_raw
            logger.warning("🔍 No YAML block found, using raw snapshot")
    
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
                actions.append({"type": "navigate", "url": m.group(1)})
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

        # getByLabel('text')
        m = re.search(r"getByLabel\(['\"]([^'\"]+)['\"]\)", locator_expr)
        if m:
            return self._snapshot_search(snapshot, label=m.group(1))

        # getByText('text')
        m = re.search(r"getByText\(['\"]([^'\"]+)['\"]\)", locator_expr)
        if m:
            return self._snapshot_search(snapshot, text=m.group(1))

        # getByTestId('id')
        m = re.search(r"getByTestId\(['\"]([^'\"]+)['\"]\)", locator_expr)
        if m:
            return self._snapshot_search(snapshot, testid=m.group(1))

        # getByPlaceholder('text')
        m = re.search(r"getByPlaceholder\(['\"]([^'\"]+)['\"]\)", locator_expr)
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
        The snapshot format is:
            - button "Login" [ref=e1]
            - textbox "Email" [ref=e2]
        
        Priority: interactive elements (textbox, button, input, etc.) 
        over generic containers.
        """
        best_ref = None
        logger.info(f"🔍 SNAPSHOT_SEARCH: role='{role}', name='{name}', label='{label}'")
        for line in snapshot.splitlines():
            m = re.search(r"\[ref=([^\]]+)\]", line)
            if not m:
                continue
            ref = m.group(1)
            ll = line.lower()
            
            # Check if this line is an interactive element
            is_interactive = any(
                t in line for t in ["textbox", "button", "input", "select", 
                                    "textarea", "checkbox", "radio", "combobox",
                                    "link", "option", "menuitem"]
            )

            def matches() -> bool:
                if role and name:
                    return role.lower() in ll and name.lower() in ll
                elif role:
                    return role.lower() in ll
                elif label:
                    return label.lower() in ll
                elif text:
                    return text.lower() in ll
                elif testid:
                    return testid.lower() in ll
                elif placeholder:
                    return placeholder.lower() in ll
                elif selector:
                    words = re.sub(r"[#.\[\]='\"{}>~+*^$|():]", " ", selector).split()
                    return any(len(w) > 2 and w.lower() in ll for w in words)
                return False

            if matches():
                # Ignore les lignes qui contiennent plusieurs refs (parents avec enfants)
                if line.count("[ref=") > 1:
                    continue
                if is_interactive:
                    logger.info(f"🔍 SNAPSHOT_MATCH: returning interactive ref={ref}")
                    return ref
                if best_ref is None:
                    best_ref = ref

        # Si aucun élément interactif trouvé, retourne le premier match générique
        logger.info(f"🔍 SNAPSHOT_MATCH: returning best_ref={best_ref}")
        return best_ref

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
