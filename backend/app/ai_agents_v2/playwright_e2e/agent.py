import asyncio
import json
import logging
import re
import time
from typing import Dict, Any, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langfuse import observe
from langfuse import get_client as get_langfuse_client

from app.core.config import settings
from app.core.observability import fire_evaluation, get_trace_callback
from app.llm.llm_control import create_llm, create_llm_for_model
from .tools import PlaywrightMCPClient
from .prompts import (
    MAPPING_SYSTEM, MAPPING_USER,
    REF_RESOLVER_SYSTEM, REF_RESOLVER_USER,
    RECOVERY_SYSTEM, RECOVERY_USER,
    REACT_VERIFY_SYSTEM, REACT_VERIFY_USER,
)
from .config import LLM_MAX_TOKENS, LLM_MODEL, LLM_TEMPERATURE, APP_BASE_URL, PLACEHOLDER_PREFIX, DEBUG

logger = logging.getLogger(__name__)

# Keyword filter for DOM compression — keeps only lines the LLM needs
_DOM_KEYWORDS = (
    # Core interactive elements
    "button", "input", "label", "link", "heading",
    "aria", "role", "select", "textarea", "checkbox", "radio",
    "placeholder", "name=", "value=", "textbox",
    # Dynamic feedback elements (error messages, toasts)
    "alert", "status",
    # Custom ARIA roles found in component libraries
    "combobox", "listbox", "option", "menuitem", "menubar",
    "tab", "tablist", "tabpanel",
    "tree", "treeitem", "grid", "row", "cell", "columnheader",
    "dialog", "alertdialog", "tooltip", "modal",
    "switch", "slider", "spinbutton", "searchbox", "progressbar",
    "banner", "main", "form", "navigation",
    # File upload areas
    "upload", "file", "img", "figure",
    # State attributes (disabled fields, selected options, expanded menus)
    "disabled", "checked", "selected", "expanded", "pressed",
    "required", "readonly", "invalid", "busy",
    # Common data-* attributes used as locators
    "data-testid", "data-cy", "data-id", "data-value",
)
_DOM_MAX_LINES = 400


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


def _looks_like_login_page(snapshot: str) -> bool:
    """
    Return True if the DOM snapshot suggests the browser is on a login/auth page.
    Heuristic: has a password field + email/username field but no dashboard-level
    navigation that would indicate an authenticated session.
    """
    s = snapshot.lower()
    # Bilingual EN/FR — the target app may render labels in French
    # ("Mot de passe", "Se connecter", "Connexion") which the old English-only
    # check missed, so auto-login never fired.
    has_password = any(kw in s for kw in ("password", "mot de passe", "passe", "pwd"))
    has_email = any(kw in s for kw in (
        "email", "e-mail", "courriel", "username", "identifiant", "utilisateur",
        "sign in", "log in", "signin", "connexion", "se connecter",
    ))
    has_authenticated_nav = any(kw in s for kw in (
        "dashboard", "logout", "sign out", "signout", "profile", "sidebar",
        "navigation", "navbar", "menu", "home", "projects",
        "déconnexion", "tableau de bord", "accueil", "se déconnecter",
    ))
    return has_password and has_email and not has_authenticated_nav


def _is_auth_test_case(tc: dict) -> bool:
    """
    Return True if the test case is about authentication itself (login, register,
    logout, session). For these, we do NOT auto-login — the test is the auth flow.
    """
    auth_keywords = (
        "login", "log in", "sign in", "signin", "register", "inscription",
        "create account", "signup", "sign up", "disconnect", "logout",
        "log out", "session", "password reset", "forgot password",
        "connexion", "déconnexion", "créer un compte",
    )
    # Use `or ""` (not just .get default) — the keys exist but may hold None.
    haystack = " ".join([
        tc.get("title") or "",
        tc.get("description") or "",
        tc.get("gherkin_source") or "",
    ]).lower()
    return any(kw in haystack for kw in auth_keywords)


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

    @observe(name="playwright_merged_agent")
    async def run(
        self,
        script_v1: str,
        app_url: str = APP_BASE_URL,
        test_case_id: Optional[str] = None,
        headless: Optional[bool] = None,
        browser: Optional[str] = None,
        on_step=None,
        page_snapshots: Optional[Dict[str, str]] = None,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute script_v1 against the live application.

        page_snapshots: pre-captured { page_label: compressed_dom } from the service
        pre-flight step. When provided, the landing-page snapshot is injected as the
        initial DOM cache so the first browser_snapshot call is skipped, saving one
        round-trip. Scripts generated with multi-page snapshots will also have fewer
        (or zero) placeholders, making the whole resolution phase faster.
        """
        start = time.time()
        actual_headless = headless if headless is not None else True
        actual_browser = browser if browser is not None else "chromium"

        get_langfuse_client().update_current_span(
            input={"script_v1": script_v1, "app_url": app_url, "test_case_id": test_case_id},
            metadata={"browser": actual_browser, "headless": actual_headless},
        )

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

        logger.info(
            f"Executing {len(actions)} actions with {len(placeholders)} placeholder(s) to resolve"
            + (f" | pre-cached pages: {list(page_snapshots.keys())}" if page_snapshots else "")
        )

        accumulated_mapping: Dict[str, str] = {}
        steps_passed = 0
        steps_failed = 0
        step_details: List[Dict[str, Any]] = []
        screenshot_b64: Optional[str] = None
        # Pre-load landing DOM cache from pre-flight snapshots — skips first browser_snapshot call
        initial_snapshot = (page_snapshots or {}).get("landing")
        current_snapshot_text: Optional[str] = initial_snapshot
        effective_model = model_id or LLM_MODEL
        llm = create_llm_for_model(effective_model, LLM_TEMPERATURE, LLM_MAX_TOKENS)

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
                                    current_snapshot_text = await self._safe_snapshot(tools)

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

                        # Click may trigger navigation, a dialog, or dynamic DOM update →
                        # always re-stabilise (also handles any post-click alerts via _safe_snapshot)
                        if atype == "click":
                            current_snapshot_text = await self._wait_for_dom_stable(
                                tools, max_wait=6.0, check_interval=0.5, stable_checks=2
                            )

                        success = True

                except Exception as first_err:
                    logger.warning(f"Step {i + 1} failed ({first_err}) — self-correcting")
                    # Invalidate snapshot cache — the page state is unknown after a failure
                    current_snapshot_text = None
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
                        screenshot_dir = settings.SCREENSHOTS_DIR
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
            current = await self._safe_snapshot(tools)

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

    # ── Safe snapshot (auto-dismisses blocking dialogs) ─────────────────────────

    _MODAL_ERROR_MARKER = "does not handle the modal state"

    async def _safe_snapshot(self, tools: dict) -> str:
        """
        Take a DOM snapshot, transparently handling any blocking modal/dialog.

        The MCP server can signal a blocking dialog either as error text in the
        response body OR by raising an exception from ainvoke — both forms are
        caught and handled identically so the caller always gets a usable snapshot.

        Returns the snapshot text ready for `_extract_snapshot_text`-consumers.
        Always returns a string — empty string on total failure.
        """
        if "browser_snapshot" not in tools:
            return ""

        # Catch both error-text responses AND ainvoke exceptions
        try:
            raw = str(await tools["browser_snapshot"].ainvoke({}))
        except Exception as e:
            raw = str(e)
            logger.debug(f"browser_snapshot raised (likely modal): {e}")

        if self._MODAL_ERROR_MARKER not in raw:
            return self._extract_snapshot_text(raw)

        # ── Modal is blocking the snapshot ───────────────────────────────────
        logger.warning("Modal/dialog detected — auto-dismissing before retry")

        # "alert" has only one button (OK = accept); confirm/prompt should be
        # dismissed (Cancel) so we never execute a destructive action by accident.
        raw_lower = raw.lower()
        # alerts only have OK (accept=True); confirm/prompt use cancel (accept=False)
        accept_dialog = '"alert"' in raw_lower or '"beforeunload"' in raw_lower

        if "browser_handle_dialog" in tools:
            try:
                await tools["browser_handle_dialog"].ainvoke({"accept": accept_dialog})
                # Give the page time to process the dismissal and re-render
                await asyncio.sleep(1.0)
                try:
                    raw2 = str(await tools["browser_snapshot"].ainvoke({}))
                except Exception as e2:
                    raw2 = str(e2)
                if self._MODAL_ERROR_MARKER not in raw2:
                    logger.info(f"Dialog {'accepted' if accept_dialog else 'dismissed'} — snapshot succeeded")
                    return self._extract_snapshot_text(raw2)
                logger.warning("Second snapshot still blocked by a modal — returning raw")
                return self._extract_snapshot_text(raw2)
            except Exception as e:
                logger.warning(f"Dialog dismiss failed: {e}")

        # Last resort: return whatever we have (might be error text)
        return self._extract_snapshot_text(raw)

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

            current_snapshot_text: Optional[str] = None  # shared cache

            for i, action in enumerate(actions):
                label = self._action_label(i + 1, action)
                atype = action["type"]
                try:
                    await self._execute_single_action(tools, action, snapshot_text=current_snapshot_text)
                    steps_passed += 1
                    detail = {"step": label, "status": "passed"}
                    step_details.append(detail)
                    logger.info(f"✅ {label}")
                    if on_step:
                        await on_step(label, "passed")
                    if atype in ("navigate", "click"):
                        current_snapshot_text = await self._wait_for_dom_stable(
                            tools, max_wait=6.0, check_interval=0.5, stable_checks=2
                        )
                except Exception as e:
                    steps_failed += 1
                    detail = {"step": label, "status": "failed", "error": str(e)}
                    step_details.append(detail)
                    logger.warning(f"❌ {label}: {e}")
                    if on_step:
                        await on_step(label, "failed", error=str(e))
                    current_snapshot_text = None  # invalidate after failure
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
                            screenshot_dir = settings.SCREENSHOTS_DIR
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
        current_snapshot_text: Optional[str] = None  # shared cache — avoids one snapshot per action

        for i, action in enumerate(actions):
            label = self._action_label(i + 1, action)
            atype = action["type"]
            try:
                await self._execute_single_action(tools, action, snapshot_text=current_snapshot_text)
                steps_passed += 1
                step_details.append({"step": label, "status": "passed"})
                logger.info(f"✅ {label}")
                if on_step:
                    await on_step(label, "passed")
                # Navigate or click can change page state — refresh snapshot cache
                if atype in ("navigate", "click"):
                    current_snapshot_text = await self._wait_for_dom_stable(
                        tools, max_wait=6.0, check_interval=0.5, stable_checks=2
                    )
            except Exception as e:
                steps_failed += 1
                step_details.append({"step": label, "status": "failed", "error": str(e)})
                logger.warning(f"❌ {label}: {e}")
                if on_step:
                    await on_step(label, "failed", error=str(e))
                current_snapshot_text = None  # invalidate stale cache after failure

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
        page_snapshots: Optional[Dict[str, str]] = None,
        suite_continuation: bool = False,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a script using an already-open MCP tools dict.
        Used by run_suite_smart for the shared-browser-session optimisation —
        the caller opens PlaywrightMCPClient once for the whole suite and passes
        the tools dict here so we never pay the browser launch cost per TC.

        page_snapshots: pre-captured multi-page DOM from the pre-flight step.
        The landing snapshot is pre-loaded as the initial DOM cache.

        suite_continuation: True for TC index > 0 in a suite run. Enables smart
        session-preservation logic — skips the initial root navigate when the
        browser is already on an authenticated page, preventing TC N's
        page.goto(app_url) from bouncing through a login-page redirect and
        accidentally filling login fields with the test case's own data.
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
        # Pre-load landing snapshot from pre-flight data — avoids one browser_snapshot call
        current_snapshot_text: Optional[str] = (page_snapshots or {}).get("landing")
        effective_model = model_id or LLM_MODEL
        llm = create_llm_for_model(effective_model, LLM_TEMPERATURE, LLM_MAX_TOKENS)

        for i, action in enumerate(actions):
            label = self._action_label(i + 1, action)
            success = False
            error_msg: Optional[str] = None

            try:
                atype = action["type"]

                if atype == "navigate":
                    target_url = action["url"]

                    # Suite continuation: if this is the first action and it targets the
                    # root app URL, check whether we're already on an authenticated page.
                    # If yes, skip — avoids the pattern where page.goto(app_url) triggers
                    # a login-redirect and the next fill() hits the login form instead of
                    # the intended form in the test case.
                    if suite_continuation and i == 0:
                        snap = await self._safe_snapshot(tools)
                        current_snapshot_text = snap
                        norm_target = target_url.rstrip("/")
                        norm_base = app_url.rstrip("/")
                        is_root_nav = (norm_target == norm_base or norm_target == norm_base + "/")
                        if is_root_nav and not _looks_like_login_page(snap):
                            logger.info(
                                "Suite continuation: skipping redundant root navigate "
                                f"to {target_url} — already on an authenticated page"
                            )
                            success = True
                            continue

                    await tools["browser_navigate"].ainvoke({"url": target_url})
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
                                current_snapshot_text = await self._safe_snapshot(tools)
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
                current_snapshot_text = None  # invalidate stale cache after failure
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

    # ════════════════════════════════════════════════════════════════════════
    # TRUE ReAct VERIFICATION AGENT
    # Executes a test case against the live app by reading the DOM and letting
    # the LLM drive the MCP tools (bind_tools). Works WITH or WITHOUT a script_v1.
    # Produces a correct script_v2 reconstructed from what actually worked.
    # ════════════════════════════════════════════════════════════════════════

    # Tools the LLM is allowed to drive in the ReAct loop. Screenshot/close are
    # handled by us, not the model, so they are excluded from bind_tools.
    _REACT_TOOL_NAMES = frozenset({
        "browser_navigate", "browser_snapshot", "browser_click", "browser_type",
        "browser_press_key", "browser_select_option", "browser_wait_for",
        "browser_handle_dialog", "browser_hover", "browser_file_upload",
        "browser_navigate_back",
    })

    _MAX_REACT_STEPS = 22  # hard cap on LLM turns to bound cost/time

    async def run_react(
        self,
        tools: dict,
        test_case: Dict[str, Any],
        app_url: str = APP_BASE_URL,
        test_case_id: Optional[str] = None,
        on_step=None,
        script_v1_hint: Optional[str] = None,
        suite_continuation: bool = False,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Drive the live application from the test case using a real ReAct loop.

        The test case (Gherkin + expected results) is the oracle. The LLM observes
        the DOM, decides each MCP tool call itself, and we record every successful
        action to rebuild a clean, replayable script_v2.

        Returns the standard _result(...) dict, fully compatible with the suite
        executor and single-TC persistence path.
        """
        start = time.time()

        if not {"browser_navigate", "browser_snapshot"}.issubset(tools):
            return self._result(
                script_v1_hint or "", "error", 0, 0, 0,
                "Required MCP tools not available", time.time() - start,
                locator_mapping={},
            )

        effective_model = model_id or LLM_MODEL
        # Each ReAct turn emits either ONE tool call or a VERDICT with per-result
        # justification. 700 tokens was too small — the verdict got truncated before
        # "VERDICT: PASSED" could appear, causing every run to show as failed.
        base_llm = create_llm_for_model(effective_model, LLM_TEMPERATURE, 1500)

        # Bind only the safe, drivable tools so the model picks refs itself
        bindable = [t for name, t in tools.items() if name in self._REACT_TOOL_NAMES]
        try:
            llm = base_llm.bind_tools(bindable)
        except Exception as e:
            logger.error(f"ReAct: bind_tools failed ({e}) — model may lack tool support")
            return self._result(
                script_v1_hint or "", "error", 0, 0, 0,
                f"bind_tools unsupported: {e}", time.time() - start, locator_mapping={},
            )

        # ── Land on the app and capture the first observation ───────────────────
        if not suite_continuation:
            try:
                await tools["browser_navigate"].ainvoke({"url": app_url})
            except Exception as e:
                logger.warning(f"ReAct initial navigate failed: {e}")
        latest_snapshot = await self._wait_for_dom_stable(
            tools, max_wait=8.0, check_interval=0.6, stable_checks=2
        )

        # ── Auto-login if the app shows a login page but this TC is not an auth test ──
        from app.core.config import settings as _settings
        _is_login_pg = _looks_like_login_page(latest_snapshot)
        _is_auth_tc = _is_auth_test_case(test_case)
        logger.info(
            f"🔐 AUTO-LOGIN decision: suite_continuation={suite_continuation} | "
            f"looks_like_login_page={_is_login_pg} | is_auth_test={_is_auth_tc} | "
            f"creds_set={bool(_settings.TEST_USER_EMAIL and _settings.TEST_USER_PASSWORD)} "
            f"→ will_auto_login={(not suite_continuation) and _is_login_pg and (not _is_auth_tc) and bool(_settings.TEST_USER_EMAIL and _settings.TEST_USER_PASSWORD)}"
        )
        if (
            not suite_continuation
            and _is_login_pg
            and not _is_auth_tc
            and _settings.TEST_USER_EMAIL
            and _settings.TEST_USER_PASSWORD
        ):
            logger.info(f"ReAct: landing on login page for non-auth TC — auto-logging in as {_settings.TEST_USER_EMAIL}")
            snap_after_login = await self._auto_login(
                tools, _settings.TEST_USER_EMAIL, _settings.TEST_USER_PASSWORD
            )
            if snap_after_login:
                latest_snapshot = snap_after_login

        title = test_case.get("title", "Test case")
        tc_block = self._format_tc_for_react(test_case)
        hint = (script_v1_hint or "(none — work directly from the test case)")[:1200]

        recorded_lines: List[str] = []   # → script_v2 body
        locator_mapping: Dict[str, str] = {}
        step_details: List[Dict[str, Any]] = []
        action_log: List[str] = []       # textual memory injected into each fresh prompt
        steps_passed = 0
        steps_failed = 0
        verdict_text: Optional[str] = None
        last_sig: Optional[tuple] = None   # anti-loop: signature of the last action
        repeat_count = 0
        llm_errors = 0
        filled_fields: set = set()         # fields already typed into (not visible in DOM)
        nudge = ""
        submit_nudge_used = False           # only nudge once about a forgotten submit click
        cb = get_trace_callback()
        invoke_config = {"callbacks": [cb]} if cb else {}

        # Stateless re-prompt loop: each turn sends a FRESH [System, Human] with the
        # live DOM + an action log. No tool-role messages are accumulated, so Groq's
        # strict tool_call_id history rules can never be violated.
        snapshot_only_streak = 0  # consecutive turns where model only called browser_snapshot
        for turn in range(self._MAX_REACT_STEPS):
            log_text = "\n".join(action_log[-14:]) if action_log else "(nothing done yet)"
            filled_text = ", ".join(sorted(filled_fields)) if filled_fields else "none yet"
            all_real_actions = [a for a in action_log if not a.startswith("observed")]
            logger.info(
                f"\n{'='*64}\n"
                f"🎬 ReAct TURN {turn}/{self._MAX_REACT_STEPS} | "
                f"real_actions={len(all_real_actions)} | snap_streak={snapshot_only_streak} | "
                f"passed={steps_passed} failed={steps_failed} | llm_errors={llm_errors}\n"
                f"{'='*64}\n"
                f"📋 ACTION LOG:\n{log_text}"
            )
            verdict_cue = (
                "\n\n⚠️ ALL STEPS APPEAR DONE — do NOT call any more tools. "
                "Reply NOW with your VERDICT: PASSED or VERDICT: FAILED, then justify each expected result."
                if snapshot_only_streak >= 2 or (all_real_actions and len(all_real_actions) >= 3 and turn >= 8)
                else (
                    "\n\nIF every Gherkin step is done AND every expected result is verified → "
                    "reply with VERDICT: PASSED (or FAILED) in plain text, NO tool call. "
                    "Otherwise call EXACTLY ONE tool for the next unfinished step. "
                    "NOTE: the snapshot below is fresh — only call browser_snapshot if you need "
                    "a NEW view after an action you are about to perform."
                )
            )
            human = (
                REACT_VERIFY_USER.format(app_url=app_url, test_case=tc_block, script_v1_hint=hint)
                + f"\n\nACTIONS DONE SO FAR (do NOT repeat these — they already succeeded):\n{log_text}"
                + f"\n\nFIELDS ALREADY FILLED (do NOT fill these again): {filled_text}"
                + f"\n\nCURRENT PAGE SNAPSHOT (act using these refs):\n{_compress_dom(latest_snapshot)}"
                + "\n\nNOTE: filled input values are NOT shown in the snapshot — if the action log "
                  "says you already filled a field, TRUST IT and move on; do not fill it again."
                + verdict_cue
                + (f"\n\n⚠️ {nudge}" if nudge else "")
            )
            messages = [
                SystemMessage(content=REACT_VERIFY_SYSTEM),
                HumanMessage(content=human),
            ]
            nudge = ""  # consumed
            if DEBUG:
                logger.info(f"📨 FULL HUMAN PROMPT (turn {turn}):\n{human}\n{'-'*64}")
            else:
                logger.info(
                    f"👁️  SNAPSHOT sent to LLM ({len(_compress_dom(latest_snapshot))} chars compressed)"
                    + (f" | ⚠️ NUDGE active" if "nudge" in human.lower() else "")
                )

            try:
                ai = await llm.ainvoke(messages, config=invoke_config)
                tool_calls = getattr(ai, "tool_calls", None) or []
                content = ai.content or ""
                llm_errors = 0
                _preview = content if len(content) <= 500 else content[:500] + "…[truncated]"
                logger.info(
                    f"🧠 LLM RESPONSE → tool_calls={[c.get('name') for c in tool_calls] or 'NONE'}\n"
                    f"   content={_preview!r}"
                )
            except Exception as e:
                recovered = self._recover_tool_call_from_error(e)
                if recovered:
                    logger.info(f"ReAct: recovered malformed tool call → {recovered['name']}")
                    tool_calls, content = [recovered], ""
                    llm_errors = 0
                else:
                    llm_errors = locals().get("llm_errors", 0) + 1
                    logger.error(f"ReAct: LLM call failed at turn {turn} ({llm_errors}/3): {e}")
                    if llm_errors >= 3:
                        step_details.append({"step": f"LLM turn {turn}", "status": "failed", "error": str(e)[:160]})
                        break
                    # Tell the LLM to avoid special characters in element descriptions
                    # so the next turn doesn't generate the same broken tool call.
                    nudge = ("Your last tool call was rejected because the element name contained "
                             "a special character (apostrophe). On your next call, identify the "
                             "element by its [ref=eXX] value from the snapshot instead of its label.")
                    continue

            # No tool call → final verdict
            if not tool_calls:
                verdict_text = content.strip()
                # GUARD — form filled but never submitted: the agent typed/selected
                # fields but never clicked a Create/Save button, then declared the
                # item "not created". Nudge it ONCE to click submit before judging.
                if not submit_nudge_used:
                    _SUBMIT_KW = ("submit", "save", "create", "enregistr", "créer",
                                  "creer", "ajouter", "valider", "soumettre", "confirm")
                    filled = any(
                        a.startswith("✓ type") or a.startswith("✓ select_option")
                        for a in action_log
                    )
                    clicked_submit = any(
                        a.startswith("✓ click") and any(kw in a.lower() for kw in _SUBMIT_KW)
                        for a in action_log
                    )
                    if filled and not clicked_submit and "FAILED" in verdict_text.upper():
                        submit_nudge_used = True
                        nudge = ("You filled the form but NEVER clicked the submit button "
                                 "(Save / Create / Enregistrer / Créer / Ajouter). A form that "
                                 "is not submitted creates NOTHING. Take a snapshot, find the "
                                 "submit/create button, CLICK it, wait, then re-verify — do "
                                 "NOT give a verdict yet.")
                        logger.info(
                            "ReAct: form filled but no submit click detected — "
                            "nudging to click Create before accepting the FAILED verdict"
                        )
                        verdict_text = None
                        continue
                logger.info(f"🧠 ReAct verdict received at turn {turn}")
                break

            if content and re.search(r"VERDICT\s*:\s*(PASSED|FAILED)", content, re.IGNORECASE):
                verdict_text = content.strip()
                logger.info(f"🧠 ReAct verdict in content alongside tool_call — captured at turn {turn}")
                break

            # Execute ONE action per turn, then re-observe and re-prompt
            call = tool_calls[0]
            name = call.get("name", "")
            args = self._normalize_react_args(name, call.get("args", {}) or {})
            logger.info(f"⚙️  EXECUTE → {name}({json.dumps(args, ensure_ascii=False)[:300]})")

            if name not in tools:
                action_log.append(f"tried unavailable tool '{name}'")
                continue

            # ── Anti-loop guard: detect the model repeating the same action ─────
            sig = (
                name,
                str(args.get("ref", "")),
                str(args.get("text", args.get("value", ""))),
            )
            if name != "browser_snapshot" and sig == last_sig:
                repeat_count += 1
                if repeat_count >= 3:
                    logger.info("ReAct: stuck repeating an action → forcing verdict evaluation")
                    nudge = ("You are repeating the same action. Stop. Click the final submit/create "
                             "button if not yet done, then give your VERDICT.")
                    # one last nudged turn, then bail if it persists
                    if repeat_count >= 5:
                        break
                action_log.append(f"(ignored duplicate {name} — already done)")
                nudge = ("You just repeated an action already in the log. Do the NEXT step instead "
                         "(e.g., click the create/submit button), or give your VERDICT.")
                continue
            repeat_count = 0
            last_sig = sig

            try:
                raw = await tools[name].ainvoke(args)
                logger.info(f"📤 {name} RETURNED: {str(raw)[:250]!r}")
                result_text = self._extract_snapshot_text(str(raw))
                if "[ref=" in result_text:
                    latest_snapshot = result_text

                if name == "browser_snapshot":
                    action_log.append("observed the page (snapshot)")
                    snapshot_only_streak += 1
                else:
                    snapshot_only_streak = 0
                    ts_line = self._react_action_to_ts(name, args, latest_snapshot)
                    if ts_line:
                        recorded_lines.append(ts_line)
                        desc = args.get("element") or args.get("ref") or name
                        locator_mapping[str(desc)] = ts_line
                    friendly = self._friendly_target_from_result(str(raw))
                    label = self._react_step_label(name, args, target=friendly)
                    steps_passed += 1
                    step_details.append({"step": label, "status": "passed"})
                    action_log.append(f"✓ {label}")
                    # Remember filled fields so the model stops re-filling what it
                    # cannot see (input values are absent from the snapshot).
                    if name == "browser_type":
                        fld = self._ref_to_locator(latest_snapshot, args.get("ref", "")) or args.get("element", "")
                        fld_name = re.search(r"name:\s*'([^']+)'", fld or "")
                        filled_fields.add(fld_name.group(1) if fld_name else (args.get("element") or args.get("ref", "")))
                    if on_step:
                        await on_step(label, "passed")

                # After a page transition, refresh the DOM so the next turn sees reality
                if name in ("browser_click", "browser_navigate", "browser_navigate_back",
                            "browser_press_key", "browser_handle_dialog", "browser_select_option"):
                    latest_snapshot = await self._wait_for_dom_stable(
                        tools, max_wait=6.0, check_interval=0.5, stable_checks=2
                    )

            except Exception as e:
                # MCP returns markdown errors like "### Error\n<real reason>\n### Ran…".
                # Keep the REAL reason, not just the "### Error" header line, so the
                # failure is diagnosable and the model knows WHY the ref didn't work.
                snapshot_only_streak = 0
                err = self._extract_tool_error(e)
                logger.warning(f"ReAct tool '{name}' failed: {err}")
                label = self._react_step_label(name, args)
                steps_failed += 1
                step_details.append({"step": label, "status": "failed", "error": err})
                action_log.append(f"✗ {label} FAILED: {err}")
                if on_step:
                    await on_step(label, "failed", error=err)
                # Re-observe so the model can recover on the next turn …
                try:
                    latest_snapshot = await self._safe_snapshot(tools)
                except Exception:
                    pass
                # … and tell it the ref it just used is dead so it stops hammering
                # the same stale/uneditable element and picks a fresh one instead.
                bad_ref = args.get("ref", "") or args.get("target", "")
                if bad_ref:
                    nudge = (
                        f"Your action on [ref={bad_ref}] FAILED: {err}. That ref is "
                        f"stale or not interactable. Look at the CURRENT snapshot and "
                        f"choose a DIFFERENT fresh ref for this step — do NOT reuse "
                        f"[ref={bad_ref}]. If the field truly isn't on the page, skip "
                        f"it and continue."
                    )
                    # Clear the anti-loop signature so a genuine retry on a NEW ref
                    # isn't instantly suppressed as a duplicate.
                    last_sig = None

        # ── Forced verdict: the loop broke out WITHOUT a plain-text verdict ──────
        # This happens when the anti-loop guard bails (the model kept re-emitting
        # the same action and never produced a VERDICT). The whole TC was about to
        # be marked "no verdict = fail" even though most steps succeeded. Make ONE
        # final tool-LESS call so the model MUST judge PASS/FAIL from what it did,
        # instead of defaulting to failure just because it got stuck clicking.
        if verdict_text is None and action_log:
            try:
                verdict_text = await self._force_react_verdict(
                    base_llm, tc_block, action_log, latest_snapshot, invoke_config
                )
                if verdict_text:
                    logger.info(f"ReAct: forced verdict after loop break → {verdict_text[:60]}")
            except Exception as e:
                logger.warning(f"ReAct: forced verdict call failed: {e}")

        # ── Parse the verdict + fold its expectation lines into step_details ────
        logger.info(
            f"\n{'#'*64}\n"
            f"🏁 ReAct VERDICT PARSING\n"
            f"   verdict_text = {verdict_text!r}\n"
            f"{'#'*64}"
        )
        passed_verdict, justification = self._parse_react_verdict(verdict_text)
        logger.info(
            f"   → passed_verdict={passed_verdict} | justification={justification}\n"
            f"   → reason: {'no verdict text (loop hit cap or got stuck)' if verdict_text is None else ('regex matched VERDICT: PASSED' if passed_verdict else 'VERDICT: PASSED not found in text')}"
        )
        for jline in justification:
            # A justification line is a FAILURE only if it carries a ❌ marker.
            # The ✅/❌ can appear ANYWHERE in the line — the LLM often writes
            # "Expected result: ✅ verified" rather than "✅ Expected result",
            # so the old startswith("✅") check wrongly flagged verified results
            # as failures. Presence of ❌ = unmet expectation; otherwise passed.
            failed_line = "❌" in jline
            step_details.append({
                "step": jline.lstrip("✅❌ -").strip()[:200],
                "status": "failed" if failed_line else "passed",
            })
            if failed_line:
                steps_failed += 1
            else:
                steps_passed += 1

        if verdict_text is None:
            # Loop hit the step cap without a verdict → inconclusive = failure
            steps_failed += 1
            justification = justification or ["❌ Agent did not reach a verdict within the step budget"]
            passed_verdict = False

        # ── Final screenshot (always — needed for failed TCs) ───────────────────
        screenshot_b64 = await self._capture_screenshot(tools, test_case_id)

        script_v2 = self._build_react_script_v2(title, app_url, recorded_lines)
        status = "completed" if passed_verdict else "failed"
        error = None if passed_verdict else " | ".join(justification)[:500]

        logger.info(
            f"ReAct done — verdict={'PASSED' if passed_verdict else 'FAILED'}, "
            f"{steps_passed} passed / {steps_failed} failed, {len(recorded_lines)} script lines"
        )

        result = self._result(
            script_v2, status,
            steps_passed=steps_passed, steps_failed=steps_failed,
            remaining=0, error=error, duration=time.time() - start,
            step_details=step_details, screenshot=screenshot_b64,
            locator_mapping=locator_mapping,
        )
        result["action_log"] = action_log
        return result

    # ── ReAct helpers ───────────────────────────────────────────────────────────

    def _format_tc_for_react(self, tc: Dict[str, Any]) -> str:
        """Render a test case as a compact, oracle-friendly block for the prompt."""
        lines = [f"Title: {tc.get('title', 'Untitled')}"]
        if tc.get("description"):
            lines.append(f"Description: {tc['description']}")
        pre = tc.get("preconditions") or []
        if pre:
            lines.append("Preconditions:")
            lines += [f"  - {p}" for p in pre]
        if tc.get("gherkin_source"):
            lines.append("Steps (Gherkin):")
            lines += [f"  {l}" for l in str(tc["gherkin_source"]).splitlines() if l.strip()]
        else:
            steps = tc.get("steps") or []
            if steps:
                lines.append("Steps:")
                for s in steps:
                    if isinstance(s, dict):
                        lines.append(f"  - {s.get('action', '')}"
                                     + (f" → {s.get('expected', '')}" if s.get("expected") else ""))
                    else:
                        lines.append(f"  - {s}")
        td = tc.get("test_data") or {}
        if td:
            lines.append("Test Data (use these exact values):")
            lines += [f"  {k} = {v}" for k, v in td.items()]
        er = tc.get("expected_results") or []
        if er:
            lines.append("Expected Results (verify each one is really present):")
            lines += [f"  - {e}" for e in er]
        post = tc.get("postconditions") or []
        if post:
            lines.append("Postconditions:")
            lines += [f"  - {p}" for p in post]
        return "\n".join(lines)

    async def _auto_login(self, tools: dict, email: str, password: str) -> Optional[str]:
        """
        Programmatically log into the app using the test credentials.
        Called before non-auth test cases when the landing page is still the login screen.
        Returns the snapshot after login, or None if login failed.
        """
        try:
            snap = await self._safe_snapshot(tools)
            # Find email field ref
            email_ref = None
            pass_ref = None
            btn_ref = None
            # Bilingual EN/FR field detection. The first matching field of each
            # kind wins — login forms list email before password.
            _EMAIL_KW = ("email", "e-mail", "courriel", "identifiant", "utilisateur", "username")
            _PASS_KW = ("password", "mot de passe", "passe", "pwd")
            _BTN_KW = ("connexion", "se connecter", "login", "log in", "sign in", "connecter")
            for line in snap.splitlines():
                ll = line.lower()
                is_input = ("textbox" in ll or "input" in ll or "searchbox" in ll)
                if is_input and "[ref=" in line and email_ref is None and any(k in ll for k in _EMAIL_KW):
                    m = re.search(r'\[ref=(e\d+)\]', line)
                    if m:
                        email_ref = m.group(1)
                elif is_input and "[ref=" in line and pass_ref is None and any(k in ll for k in _PASS_KW):
                    m = re.search(r'\[ref=(e\d+)\]', line)
                    if m:
                        pass_ref = m.group(1)
                elif "button" in ll and "[ref=" in line and btn_ref is None and any(kw in ll for kw in _BTN_KW):
                    m = re.search(r'\[ref=(e\d+)\]', line)
                    if m:
                        btn_ref = m.group(1)

            if not (email_ref and pass_ref):
                logger.warning("Auto-login: could not find email/password fields in login page")
                return None

            logger.info(f"Auto-login: found refs — email={email_ref}, pass={pass_ref}, btn={btn_ref}")
            # MCP browser_type requires both "ref" AND "target" (target = the ref string,
            # element = human description). Passing only "ref" causes "expected string,
            # received undefined" on the "target" field.
            await tools["browser_type"].ainvoke({"ref": email_ref, "target": email_ref, "element": "email field", "text": email})
            await tools["browser_type"].ainvoke({"ref": pass_ref, "target": pass_ref, "element": "password field", "text": password})

            # Press Enter to submit — more reliable than clicking a button ref detected
            # from the snapshot (which can match wrong elements like nav buttons that
            # appear before the form inputs in the accessibility tree, e.g. e8 instead
            # of the real submit button e19).
            await tools["browser_press_key"].ainvoke({"key": "Enter"})

            # Wait for page to change after login
            snap_after = await self._wait_for_dom_stable(tools, max_wait=8.0, check_interval=0.6, stable_checks=2)
            if not _looks_like_login_page(snap_after):
                logger.info("Auto-login: succeeded — now on authenticated page")
                return snap_after
            else:
                logger.warning("Auto-login: still on login page after submit — credentials may be wrong")
                return None
        except Exception as e:
            logger.warning(f"Auto-login failed: {e}")
            return None

    def _ref_to_locator(self, snapshot: str, ref: str) -> Optional[str]:
        """
        Reverse lookup: given an aria ref, find its snapshot line and build a
        stable Playwright locator (getByRole with the accessible name).
        """
        if not ref or not snapshot:
            return None
        for line in snapshot.splitlines():
            if f"[ref={ref}]" not in line:
                continue
            m = re.search(r'(\w+)\s+"([^"]*)"', line)
            if m:
                role, name = m.group(1), m.group(2).replace("'", "\\'")
                if name:
                    return f"page.getByRole('{role}', {{ name: '{name}' }})"
                return f"page.getByRole('{role}')"
            # No accessible name on the line — fall back to a text locator if any
            mt = re.search(r'"([^"]+)"', line)
            if mt:
                return f"page.getByText('{mt.group(1)}')"
            return None
        return None

    def _react_action_to_ts(self, name: str, args: dict, snapshot: str) -> Optional[str]:
        """Turn one executed MCP tool call into a replayable TypeScript line."""
        if name == "browser_navigate":
            return f"await page.goto('{args.get('url', '')}');"
        if name == "browser_press_key":
            return f"await page.keyboard.press('{args.get('key', 'Enter')}');"

        ref = args.get("ref") or args.get("target") or ""
        loc = self._ref_to_locator(snapshot, ref)
        if not loc:
            return None
        if name == "browser_click":
            return f"await {loc}.click();"
        if name == "browser_type":
            val = str(args.get("text", args.get("value", ""))).replace("'", "\\'")
            return f"await {loc}.fill('{val}');"
        if name == "browser_select_option":
            val = str(args.get("values", args.get("value", ""))).replace("'", "\\'")
            return f"await {loc}.selectOption('{val}');"
        if name == "browser_hover":
            return f"await {loc}.hover();"
        return None

    @staticmethod
    def _friendly_target_from_result(raw: str) -> Optional[str]:
        """Extract the REAL element name from the MCP '### Ran Playwright code' block.

        MCP returns the actual Playwright locator it ran, e.g.
        `await page.getByTestId('client-name').fill(...)`. We parse that into a
        human-readable token (`client-name`, `Clients`, …) so the step log shows
        real elements instead of the ephemeral `[ref=eXX]`. Zero LLM calls — the
        info is already in the tool response.
        """
        if not raw:
            return None
        for pat in (
            r"getByTestId\(\s*['\"]([^'\"]+)['\"]",
            r"getByRole\(\s*['\"][^'\"]+['\"]\s*,\s*\{[^}]*name:\s*['\"]([^'\"]+)['\"]",
            r"getByLabel\(\s*['\"]([^'\"]+)['\"]",
            r"getByPlaceholder\(\s*['\"]([^'\"]+)['\"]",
            r"getByText\(\s*['\"]([^'\"]+)['\"]",
        ):
            m = re.search(pat, raw)
            if m:
                return m.group(1)
        return None

    def _react_step_label(self, name: str, args: dict, target: Optional[str] = None) -> str:
        # `target` is the REAL element name parsed from the MCP response (preferred);
        # fall back to the model-supplied element description, then the raw ref.
        elem = target or args.get("element") or args.get("ref", "")
        short = name.replace("browser_", "")
        if name == "browser_navigate":
            return f"navigate → {args.get('url', '')}"
        if name == "browser_type":
            return f"type '{args.get('text', args.get('value', ''))}' into {elem}"
        if name in ("browser_click", "browser_hover"):
            return f"{short} {elem}"
        if name == "browser_press_key":
            return f"press {args.get('key', '')}"
        if name == "browser_wait_for":
            return f"wait for '{args.get('text', '')}'" if args.get("text") else "wait_for"
        return f"{short} {elem}".strip()

    def _normalize_react_args(self, name: str, args: dict) -> dict:
        """
        Reconcile the various arg shapes models emit for MCP element tools.
        Some models use 'target' for the aria ref; MCP element tools also want an
        'element' description alongside 'ref'.
        """
        args = dict(args)
        tgt = args.get("target")
        if "ref" not in args and isinstance(tgt, str) and re.match(r"^e\d+$", tgt.strip()):
            args["ref"] = tgt.strip()
        if name in ("browser_click", "browser_type", "browser_hover", "browser_select_option"):
            if "element" not in args or not args.get("element"):
                args["element"] = args.get("ref", "target element")
        if name == "browser_select_option":
            v = args.get("values", args.get("value"))
            if v is not None and not isinstance(v, list):
                args["values"] = [v]
            args.pop("value", None)
        return args

    @staticmethod
    def _recover_tool_call_from_error(err: Exception) -> Optional[dict]:
        msg = str(err)
        if "tool_use_failed" not in msg and "failed_generation" not in msg:
            return None
        m = re.search(r"<function=(\w+)>?\s*(\{.*?\})", msg, re.DOTALL)
        if not m:
            return None
        name = m.group(1)
        raw_json = m.group(2)
        # \' is not a valid JSON escape — strip the backslash so json.loads succeeds
        sanitized = raw_json.replace("\\'", "'")
        try:
            args = json.loads(sanitized)
        except Exception:
            try:
                args = json.loads(raw_json)
            except Exception:
                return None
        return {"name": name, "args": args, "id": "recovered_0"}

    @staticmethod
    def _extract_tool_error(err: Exception) -> str:
        """
        Pull the human-readable reason out of an MCP tool error.

        MCP Playwright returns markdown like:
            ### Error
            locator.fill: Element is not an <input>, <textarea> ...
            ### Ran Playwright code
            ```js ...
        `str(err).splitlines()[0]` would keep only "### Error", hiding the real
        cause. This skips markdown headers/code fences and returns the first
        meaningful line so failures are diagnosable and the model can react.
        """
        raw = str(err).strip()
        if not raw:
            return "unknown error"
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        meaningful = [
            l for l in lines
            if not l.startswith("###") and not l.startswith("```") and l != "Error"
        ]
        chosen = meaningful[0] if meaningful else (lines[0] if lines else "unknown error")
        return chosen[:200]

    @staticmethod
    def _parse_react_verdict(text: Optional[str]) -> tuple:
        """Extract (passed: bool, justification_lines: list[str]) from the final message."""
        if not text:
            return False, []
        passed = bool(re.search(r"VERDICT\s*:\s*PASSED", text, re.IGNORECASE))
        just: List[str] = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("✅") or s.startswith("❌") or s.startswith("- "):
                just.append(s.lstrip("- ").strip())
        return passed, [j for j in just if j]

    async def _force_react_verdict(
        self, base_llm, tc_block: str, action_log: List[str],
        latest_snapshot: str, invoke_config: dict,
    ) -> Optional[str]:
        """
        Last-resort verdict. Called when the ReAct loop broke out (e.g. anti-loop
        guard) without the model ever emitting a plain-text VERDICT.

        Uses the *tool-less* base LLM so the model physically cannot emit another
        tool call — it MUST answer with a verdict. This converts a "stuck but
        mostly-completed" run into a real PASS/FAIL judgment instead of an
        automatic failure.
        """
        log_text = "\n".join(action_log[-20:]) if action_log else "(nothing recorded)"
        human = (
            "You were verifying this test case against a live app but the run was "
            "stopped because you kept repeating an action.\n\n"
            f"TEST CASE:\n{tc_block}\n\n"
            f"ACTIONS YOU ACTUALLY COMPLETED:\n{log_text}\n\n"
            f"FINAL PAGE SNAPSHOT:\n{_compress_dom(latest_snapshot)}\n\n"
            "Based ONLY on the actions completed and the final page state, decide "
            "whether the test case's expected results were met. Do NOT call any tool. "
            "Reply with exactly one line 'VERDICT: PASSED' or 'VERDICT: FAILED', then "
            "one bullet (✅ or ❌) per expected result explaining why."
        )
        messages = [
            SystemMessage(content=REACT_VERIFY_SYSTEM),
            HumanMessage(content=human),
        ]
        ai = await base_llm.ainvoke(messages, config=invoke_config)
        return (ai.content or "").strip() or None

    def _build_react_script_v2(self, title: str, app_url: str, lines: List[str]) -> str:
        """Assemble a clean, replayable Playwright script from recorded actions."""
        safe_title = title.replace("'", "\\'")
        # Drop consecutive duplicate lines (the model sometimes re-fills a field)
        deduped: List[str] = []
        for l in lines:
            if not deduped or deduped[-1] != l:
                deduped.append(l)
        lines = deduped
        body = "\n".join(f"  {l}" for l in lines) if lines else "  // no actions recorded"
        # Ensure the script always opens the app even if the model skipped goto
        if not any("page.goto(" in l for l in lines):
            body = f"  await page.goto('{app_url}');\n" + body
        return (
            "import { test, expect } from '@playwright/test';\n\n"
            f"test('{safe_title}', async ({{ page }}) => {{\n"
            f"{body}\n"
            "});\n"
        )

    async def _capture_screenshot(self, tools: dict, test_case_id: Optional[str]) -> Optional[str]:
        """Take a final screenshot and return base64 — shared by ReAct + Phase 4."""
        if "browser_take_screenshot" not in tools:
            return None
        try:
            raw = await tools["browser_take_screenshot"].ainvoke({})
            b64 = self._extract_screenshot_b64(raw)
            if b64 and test_case_id:
                import os, base64 as _b64
                os.makedirs("screenshots", exist_ok=True)
                fname = f"screenshots/test_{test_case_id}_{time.strftime('%Y%m%d-%H%M%S')}.png"
                with open(fname, "wb") as f:
                    f.write(_b64.b64decode(b64))
                logger.info(f"📸 Screenshot saved: {fname}")
            return b64
        except Exception as e:
            logger.warning(f"📸 ReAct screenshot failed: {e}")
            return None

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
            props = {}
            schema = getattr(tool, "args_schema", None)
            if schema:
                # langchain may expose args_schema as a Pydantic model (v1 .schema(),
                # v2 .model_json_schema()) OR already as a plain dict JSON-schema.
                if isinstance(schema, dict):
                    props = schema.get("properties", {})
                elif hasattr(schema, "model_json_schema"):
                    props = schema.model_json_schema().get("properties", {})
                elif hasattr(schema, "schema"):
                    props = schema.schema().get("properties", {})
            if props:
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

        if atype == "scroll":
            if "browser_scroll" in tools:
                await tools["browser_scroll"].ainvoke({
                    "direction": action.get("direction", "down"),
                    "amount": action.get("amount", 300),
                })
            else:
                await asyncio.sleep(0.3)
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
                    fs = await self._safe_snapshot(tools)
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
                        fresh_snapshot = await self._safe_snapshot(tools)
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
            if "browser_snapshot" in tools:
                snap = await self._safe_snapshot(tools)
                expected = action.get("url", "")
                if expected not in snap:
                    raise RuntimeError(f"URL mismatch: expected '{expected}' not found in page")
            logger.info(f"✅ Assert URL: {action.get('url', '')[:60]}")

        elif atype == "hover":
            if "browser_hover" not in tools:
                logger.warning("browser_hover not available — skipping hover step")
                return
            await tools["browser_hover"].ainvoke(
                self._elem_params(tools["browser_hover"], ref, locator_expr)
            )
            await asyncio.sleep(0.3)

        elif atype == "upload":
            if "browser_file_upload" not in tools:
                raise RuntimeError("browser_file_upload not available")
            await tools["browser_file_upload"].ainvoke({
                **self._elem_params(tools["browser_file_upload"], ref, locator_expr),
                "paths": action.get("files", []),
            })
            await asyncio.sleep(0.5)


    async def _scroll_until_visible(
        self,
        tools: dict,
        locator_expr: str,
        max_scrolls: int = 5,
        scroll_amount: int = 500,
    ) -> tuple:
        """
        Scroll down in increments until the target element appears in the snapshot.

        Handles: virtual/infinite scroll lists, lazy-loaded sections, sticky-nav-obscured
        elements, and anything rendered below the initial viewport.

        Returns (ref, snapshot_text) if found, (None, None) if not found after max_scrolls.
        """
        if "browser_scroll" not in tools or "browser_snapshot" not in tools:
            return None, None

        logger.info(
            f"scroll_until_visible: element not in viewport, "
            f"scrolling up to {max_scrolls}x for '{locator_expr[:60]}'"
        )

        for attempt in range(1, max_scrolls + 1):
            await tools["browser_scroll"].ainvoke(
                {"direction": "down", "amount": scroll_amount}
            )
            await asyncio.sleep(0.5)

            snapshot = await self._safe_snapshot(tools)
            ref = self._find_ref_in_snapshot(snapshot, locator_expr)
            if ref:
                logger.info(
                    f"scroll_until_visible: found '{locator_expr[:50]}' "
                    f"after {attempt} scroll(s)"
                )
                return ref, snapshot

        logger.info(
            f"scroll_until_visible: element still not found after {max_scrolls} scrolls"
        )
        return None, None

    async def _resolve_ref(
        self, tools: dict, locator_expr: str, snapshot_text: Optional[str] = None
    ):
        """
        Find the MCP aria ref for a locator expression.

        Resolution order:
          1. Search the provided (cached) snapshot — zero extra browser calls
          2. If not found and browser_scroll is available, scroll down up to 5×
             and re-snapshot after each scroll (handles below-fold elements)
          3. Raise RuntimeError so the caller can fall back to LLM self-correction
        """
        if snapshot_text is None:
            if "browser_snapshot" not in tools:
                raise RuntimeError("browser_snapshot not available")
            snapshot_text = await self._safe_snapshot(tools)

        ref = self._find_ref_in_snapshot(snapshot_text, locator_expr)

        # Element not in current viewport — try scrolling before giving up
        if not ref:
            ref, scrolled_snapshot = await self._scroll_until_visible(tools, locator_expr)
            if ref:
                return ref, locator_expr

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
            cb = get_trace_callback()
            response = await llm.ainvoke(
                [
                    SystemMessage(content=REF_RESOLVER_SYSTEM),
                    HumanMessage(content=REF_RESOLVER_USER.format(
                        dom=dom_excerpt,
                        description=description,
                        action_type=action_type,
                    )),
                ],
                config={"callbacks": [cb]} if cb else {},
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
            cb = get_trace_callback()
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
                config={"callbacks": [cb]} if cb else {},
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

        Two-pass approach:
          Pass 1 — collect variable bindings:  const btn = page.getByLabel('Email')
          Pass 2 — parse action lines, resolving variable references inline.

        Chain modifiers (.nth(), .first(), .last(), .filter()) are stripped from
        locator expressions before matching; the snapshot search already returns
        the best available match without needing an exact index.
        """
        actions: List[Dict[str, Any]] = []

        # ── Pass 1: collect variable → locator bindings ─────────────────────
        var_map: Dict[str, str] = {}
        for line in script.splitlines():
            m = re.match(
                r'\s*(?:const|let|var)\s+(\w+)\s*=\s*(page\.[^;]+?)[\s;]*$',
                line,
            )
            if m:
                expr = m.group(2).strip().rstrip(';').strip()
                # Only store pure locator expressions (no action calls)
                if not re.search(r'\.(click|fill|type|press|hover|selectOption)\s*\(', expr):
                    var_map[m.group(1)] = expr

        # ── Pass 2: parse action lines ───────────────────────────────────────
        for line in script.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("import"):
                continue
            if re.match(r"^(test|describe)\s*\(", stripped) or stripped in ("});", "}):", "{"):
                continue

            # Resolve variable references before any pattern matching
            resolved = self._resolve_vars(stripped, var_map)

            # page.goto(url)
            m = re.search(r"page\.goto\(['\"]([^'\"]+)['\"]\)", resolved)
            if m:
                url = m.group(1)
                if url.startswith("/"):
                    url = app_url.rstrip("/") + url
                actions.append({"type": "navigate", "url": url})
                continue

            # page.waitForTimeout(ms)
            m = re.search(r"page\.waitForTimeout\((\d+)\)", resolved)
            if m:
                actions.append({"type": "wait", "ms": int(m.group(1))})
                continue

            # .click()
            if ".click()" in resolved and "page." in resolved:
                locator = self._locator_before(resolved, ".click()")
                if locator:
                    actions.append({"type": "click", "locator": locator})
                    continue

            # .fill('value')  or  .fill("value")
            m = re.search(r"\.fill\(['\"]([^'\"]*)['\"]", resolved)
            if m and "page." in resolved:
                locator = self._locator_before(resolved, ".fill(")
                if locator:
                    actions.append({"type": "fill", "locator": locator, "value": m.group(1)})
                    continue

            # .type('value')
            m = re.search(r"\.type\(['\"]([^'\"]*)['\"]", resolved)
            if m and "page." in resolved:
                locator = self._locator_before(resolved, ".type(")
                if locator:
                    actions.append({"type": "type", "locator": locator, "value": m.group(1)})
                    continue

            # .press('key')
            m = re.search(r"\.press\(['\"]([^'\"]*)['\"]", resolved)
            if m and "page." in resolved:
                actions.append({"type": "press", "key": m.group(1)})
                continue

            # .selectOption('value')
            m = re.search(r"\.selectOption\(['\"]([^'\"]*)['\"]", resolved)
            if m and "page." in resolved:
                locator = self._locator_before(resolved, ".selectOption(")
                if locator:
                    actions.append({"type": "select_option", "locator": locator, "value": m.group(1)})
                    continue

            # expect(...).toBeVisible()
            m = re.search(r"expect\((.+)\)\.toBeVisible\(\)", resolved)
            if m:
                locator_expr = m.group(1).strip()
                if "page." in locator_expr or re.search(r"getBy\w+|\.locator\(", locator_expr):
                    actions.append({"type": "assert_visible", "locator": locator_expr})
                    continue

            # waitForSelector → assert_visible
            m = re.search(r"waitForSelector\(\"\[TESTFORGEAI:\s*([^\]]+)\]\"", resolved)
            if m:
                actions.append({"type": "assert_visible", "locator": f"page.locator(\"[TESTFORGEAI: {m.group(1)}]\")"})
                continue

            # toContain('...') → assert_url
            m = re.search(r"toContain\(['\"]([^'\"]+)['\"]\)", resolved)
            if m:
                actions.append({"type": "assert_url", "url": m.group(1)})
                continue

            # expect(...).toContainText / toHaveText / toBeEnabled / toBeChecked / toHaveValue / toHaveCount
            m = re.search(
                r"expect\((.+?)\)\.(toContainText|toHaveText|toBeEnabled|toBeChecked|toHaveValue|toHaveCount)\(",
                resolved,
            )
            if m:
                locator_expr = m.group(1).strip()
                if "page." in locator_expr or re.search(r"getBy\w+|\.locator\(", locator_expr):
                    actions.append({"type": "assert_visible", "locator": locator_expr})
                    continue

            # expect(page).toHaveURL('...')
            m = re.search(r"expect\(page\)\.toHaveURL\(['\"]([^'\"]+)['\"]\)", resolved)
            if m:
                actions.append({"type": "assert_url", "url": m.group(1)})
                continue

            # .hover()
            if ".hover()" in resolved and "page." in resolved:
                locator = self._locator_before(resolved, ".hover()")
                if locator:
                    actions.append({"type": "hover", "locator": locator})
                    continue

            # .scrollIntoViewIfNeeded()
            if ".scrollIntoViewIfNeeded()" in resolved:
                actions.append({"type": "scroll", "direction": "down", "amount": 300})
                continue

            # page.mouse.wheel(deltaX, deltaY)
            m = re.search(r"mouse\.wheel\(\s*[\d.]+\s*,\s*([-\d.]+)\s*\)", resolved)
            if m:
                delta_y = float(m.group(1))
                actions.append({
                    "type": "scroll",
                    "direction": "down" if delta_y >= 0 else "up",
                    "amount": int(abs(delta_y)),
                })
                continue

            # .setInputFiles('path') or .setInputFiles(['path1', 'path2'])
            m = re.search(r"\.setInputFiles\((.+)\)", resolved)
            if m and "page." in resolved:
                locator = self._locator_before(resolved, ".setInputFiles(")
                if locator:
                    files = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1).strip())
                    actions.append({"type": "upload", "locator": locator, "files": files})
                    continue

        return actions

    @staticmethod
    def _resolve_vars(line: str, var_map: Dict[str, str]) -> str:
        """
        Inline-substitute variable references with their locator expressions.

        Example:
            var_map = {"emailInput": "page.getByLabel('Email')"}
            "await emailInput.fill('test@example.com')"
            → "await page.getByLabel('Email').fill('test@example.com')"
        """
        for var, expr in var_map.items():
            # varName.action(  →  (expr).action(  — keeps chained calls intact
            line = re.sub(r'\b' + re.escape(var) + r'\.', f'({expr}).', line)
        return line

    def _locator_before(self, line: str, action_token: str) -> Optional[str]:
        """Extract the Playwright locator expression that precedes an action token."""
        idx = line.find(action_token)
        if idx < 0:
            return None
        part = line[:idx].strip()
        # Remove leading 'await '
        part = re.sub(r"^await\s+", "", part).strip()
        # Unwrap outer parens added by _resolve_vars: (page.getByLabel('x')) → page.getByLabel('x')
        if part.startswith("(") and part.endswith(")"):
            part = part[1:-1].strip()
        # Must contain a page. locator chain
        if "page." not in part:
            return None
        # Strip trailing index/filter modifiers — snapshot search picks the best match
        # e.g.  page.getByRole('listitem').nth(2)  →  page.getByRole('listitem')
        #        page.getByLabel('Email').first()   →  page.getByLabel('Email')
        part = re.sub(r'\.(nth\(\d+\)|first\(\)|last\(\)|filter\(\{[^}]*\}\))$', '', part).strip()
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
                    if text.lower() in ll or text_n in ll:
                        return True
                    # Partial match for dynamic content: strip currency/percent symbols
                    # so "$999.99" matches a line containing "999.99", and "5% off" matches "5%"
                    core = re.sub(r'[$€£¥%,\s]', '', text).lower()
                    if core and len(core) > 2 and core in ll:
                        return True
                    # Prefix match: "Out of Stock" → try each significant word
                    words = [w for w in text.lower().split() if len(w) > 3]
                    return bool(words) and all(w in ll for w in words)
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

        # Sanitise invalid JSON escapes the LLM emits for French labels with
        # apostrophes, e.g.  'Nom d\'utilisateur'  → \' is not valid JSON (#2).
        content = content.replace("\\'", "'")

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse locator mapping JSON: {e}. Raw: {content[:300]}")
            return {}

    def _apply_mapping(self, script: str, mapping: dict) -> str:
        """
        Replace every page.locator("[PLACEHOLDER: desc]") with the real locator.
        Handles both single-quoted and double-quoted variants — TypeScript scripts
        commonly use single quotes, but some generators emit double quotes.
        Pure Python — no LLM involved.
        """
        result = script
        for description, locator in mapping.items():
            for q in ('"', "'"):
                old = f'page.locator({q}[{PLACEHOLDER_PREFIX}: {description}]{q})'
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
                    # Cherche un chemin de fichier PNG dans le texte.
                    # IMPORTANT: capture the OPTIONAL leading dot INSIDE the group —
                    # the MCP server writes to a hidden ".playwright-mcp" dir, and
                    # dropping the dot made every screenshot file lookup fail (#4).
                    if item.get("type") == "text":
                        text = item.get("text", "")
                        #path_match = re.search(r'\(([^\s)]+\.png)\)', text)
                        path_match = re.search(r'\((\.?[\w\-\/\\]+\.png)\)', text)

                        if path_match:
                            rel = path_match.group(1)
                            import os, base64
                            # The MCP server is a SEPARATE process; it writes the PNG
                            # relative to ITS own cwd (often the user's home dir), not
                            # ours. Try every plausible base dir + match by basename.
                            base_name = os.path.basename(rel)
                            candidates = [rel] if os.path.isabs(rel) else [
                                os.path.join(os.getcwd(), rel),          # /app/tmp/.playwright-mcp/...
                                #os.path.join("/app", rel),               # explicit /app base (AKS backend cwd)
                                os.path.join(os.path.expanduser("~"), rel),
                                os.path.join(os.path.expanduser("~"), ".playwright-mcp", base_name),
                                os.path.join(os.getcwd(), "backend", rel),
                                os.path.abspath(rel),
                            ]
                            for filepath in candidates:
                                try:
                                    with open(filepath, 'rb') as f:
                                        b64 = base64.b64encode(f.read()).decode()
                                    logger.info(f"📸 Loaded screenshot from file: {filepath} ({len(b64)} chars)")
                                    return b64
                                except FileNotFoundError:
                                    continue
                                except Exception as e:
                                    logger.warning(f"📸 Failed to read screenshot file {filepath}: {e}")
                            logger.warning(f"📸 Screenshot file not found in any candidate path for '{rel}'")
    
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
