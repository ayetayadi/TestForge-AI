import asyncio
import logging
import re as _re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings

from app.repositories import playwright_repository as repo
from app.ai_agents_v2.playwright_e2e.script_generator import get_script_generator
from app.ai_agents_v2.playwright_e2e.agent import PlaywrightReActAgent, _compress_dom
from app.ai_agents_v2.playwright_e2e.tools import PlaywrightMCPClient
from app.models.enums import (
    ScriptSource, ScriptValidationStatus,
    TestExecutionStatus, TestCaseResultStatus,
)

logger = logging.getLogger(__name__)

# Agent instances (global)
_script_generator = get_script_generator()
_react_agent = PlaywrightReActAgent()
_agent_instance = PlaywrightReActAgent()

# ============================================================
# PRE-FLIGHT HELPERS — multi-page snapshot capture (unchanged)
# ============================================================

_NAV_ELEMENT_PATTERNS = [
    _re.compile(r'link\s+"([^"]{2,40})"\s+\[ref=(e\d+)\]', _re.IGNORECASE),
    _re.compile(r'menuitem\s+"([^"]{2,40})"\s+\[ref=(e\d+)\]', _re.IGNORECASE),
    _re.compile(r'tab\s+"([^"]{2,40})"\s+\[ref=(e\d+)\]', _re.IGNORECASE),
]

_STOP_WORDS = frozenset({
    "the", "and", "that", "this", "with", "for", "from", "click", "then",
    "when", "given", "have", "should", "user", "button", "form", "field",
    "enter", "fill", "type", "select", "verify", "assert", "check",
})


def _extract_nav_keywords(
    steps: Optional[list] = None,
    gherkin_source: Optional[str] = None,
) -> frozenset:
    raw_text = ""
    if gherkin_source:
        raw_text += gherkin_source.lower() + "\n"
    if steps:
        for step in steps:
            if isinstance(step, dict):
                raw_text += step.get("action", "").lower() + "\n"
                raw_text += step.get("expected", "").lower() + "\n"
            elif isinstance(step, str):
                raw_text += step.lower() + "\n"

    if not raw_text.strip():
        return frozenset()

    keywords: set = set()
    nav_verb_re = _re.compile(
        r'(?:navigate|go|click|open|access|visit|go\s+to)\s+'
        r'(?:to\s+)?(?:the\s+)?([a-z][a-z\s]{2,24}?)(?:\s+(?:page|screen|section|tab|menu|panel))?'
        r'(?:\s*$|[.,;])',
        _re.IGNORECASE | _re.MULTILINE,
    )
    for m in nav_verb_re.finditer(raw_text):
        kw = m.group(1).strip()
        if 2 < len(kw) < 30 and kw not in _STOP_WORDS:
            keywords.add(kw)

    page_ref_re = _re.compile(
        r'(?:on|from|in)\s+(?:the\s+)?([a-z][a-z\s]{2,20}?)\s+'
        r'(?:page|screen|section|tab|dashboard)',
        _re.IGNORECASE,
    )
    for m in page_ref_re.finditer(raw_text):
        kw = m.group(1).strip()
        if 2 < len(kw) < 30 and kw not in _STOP_WORDS:
            keywords.add(kw)

    well_known = {
        "dashboard", "login", "register", "signup", "sign up",
        "settings", "profile", "users", "admin", "home",
        "projects", "reports", "analytics", "test cases", "test suites",
        "test plans", "risks", "jira",
    }
    for wk in well_known:
        if wk in raw_text:
            keywords.add(wk)

    return frozenset(keywords)


def _parse_nav_links(snapshot_text: str) -> List[tuple]:
    links: List[tuple] = []
    seen: set = set()
    for pattern in _NAV_ELEMENT_PATTERNS:
        for m in pattern.finditer(snapshot_text):
            text = m.group(1).strip()
            ref = m.group(2)
            text_lower = text.lower()
            if text_lower in seen:
                continue
            if any(skip in text_lower for skip in ("http", "www", "://", ".com", ".org")):
                continue
            seen.add(text_lower)
            links.append((text, ref))
    return links


async def _take_multipage_snapshot(
    app_url: str,
    steps: Optional[list] = None,
    gherkin_source: Optional[str] = None,
    max_extra_pages: int = 2,
) -> Dict[str, str]:
    try:
        nav_keywords = _extract_nav_keywords(steps, gherkin_source)
        logger.info(f"Pre-flight: app_url={app_url}, keywords={nav_keywords or 'none'}")

        async with PlaywrightMCPClient(headless=True, browser="chromium") as mcp:
            tools = {t.name: t for t in mcp.tools}
            required = {"browser_navigate", "browser_snapshot"}
            if not required.issubset(tools):
                logger.warning("Pre-flight: required MCP tools not available — skipping")
                return {}

            await tools["browser_navigate"].ainvoke({"url": app_url})
            await asyncio.sleep(2.0)
            raw = str(await tools["browser_snapshot"].ainvoke({}))
            landing_text = _agent_instance._extract_snapshot_text(raw)
            snapshots: Dict[str, str] = {"landing": _compress_dom(landing_text)}
            logger.info(f"Pre-flight: landing snapshot captured ({len(snapshots['landing'])} chars)")

            if not nav_keywords or max_extra_pages <= 0 or "browser_click" not in tools:
                return snapshots

            nav_links = _parse_nav_links(landing_text)
            logger.info(f"Pre-flight: {len(nav_links)} nav links found in landing DOM")

            visited: set = set()
            extra_count = 0

            for link_text, link_ref in nav_links:
                if extra_count >= max_extra_pages:
                    break
                link_lower = link_text.lower().strip()
                if not any(kw in link_lower or link_lower in kw for kw in nav_keywords):
                    continue
                if link_lower in visited:
                    continue

                visited.add(link_lower)
                try:
                    await tools["browser_click"].ainvoke({"element": link_text, "ref": link_ref})
                    await asyncio.sleep(1.5)
                    raw2 = str(await tools["browser_snapshot"].ainvoke({}))
                    page_text = _agent_instance._extract_snapshot_text(raw2)
                    label = link_lower.replace(" ", "_")
                    snapshots[label] = _compress_dom(page_text)
                    extra_count += 1
                    logger.info(f"Pre-flight: captured '{label}' ({len(snapshots[label])} chars)")
                    await tools["browser_navigate"].ainvoke({"url": app_url})
                    await asyncio.sleep(1.0)
                except Exception as click_err:
                    logger.warning(f"Pre-flight: click on '{link_text}' failed: {click_err}")
                    try:
                        await tools["browser_navigate"].ainvoke({"url": app_url})
                        await asyncio.sleep(1.0)
                    except Exception:
                        pass

        logger.info(f"Pre-flight complete: {len(snapshots)} snapshot(s) captured — {list(snapshots.keys())}")
        return snapshots

    except Exception as e:
        logger.warning(f"Pre-flight multi-page snapshot failed — blind generation: {e}")
        return {}


# ============================================================
# STEP EXTRACTION HELPERS (for TestCaseResult.steps JSON)
# ============================================================

def _extract_text_from_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif "text" in item:
                    texts.append(str(item["text"]))
            else:
                texts.append(str(item))
        return "\n".join(t for t in texts if t.strip())
    return str(content)


def _build_steps_json(exec_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build the JSON steps list stored in TestCaseResult.steps.
    Each item: { order, type, tool_name, content, status, error }
    """
    raw_messages = exec_result.get("raw_messages", [])
    if raw_messages:
        return _steps_from_messages(raw_messages)

    step_details = exec_result.get("step_details", [])
    if step_details:
        return _steps_from_details(step_details)

    return []


def _steps_from_messages(messages: list) -> List[Dict[str, Any]]:
    """Convert LangGraph messages to step dicts."""
    steps: List[Dict[str, Any]] = []
    order = 0
    for msg in messages:
        msg_type = type(msg).__name__

        if msg_type == "AIMessage":
            content = msg.content if isinstance(msg.content, str) else ""
            if content.strip():
                steps.append({
                    "order":   order,
                    "type":    "think",
                    "content": content[:2000],
                    "tool_name": None,
                    "status":  "success",
                })
                order += 1

            tool_calls = getattr(msg, "tool_calls", None) or []
            for tc in tool_calls:
                args = tc.get("args", {})
                args_parts = [f"{k}={str(v)[:80]!r}" for k, v in args.items()]
                content_str = f"{tc.get('name', 'unknown')}({', '.join(args_parts)})"
                steps.append({
                    "order":   order,
                    "type":    "act",
                    "content": content_str[:2000],
                    "tool_name": tc.get("name"),
                    "status":  "success",
                })
                order += 1

        elif msg_type == "ToolMessage":
            text_content = _extract_text_from_content(msg.content)
            error_keywords = ("### error", "timeouterror", "exception", "unable to", "tool error (recoverable)")
            is_error = any(kw in text_content.lower() for kw in error_keywords)
            steps.append({
                "order":   order,
                "type":    "observe",
                "content": text_content[:2000],
                "tool_name": getattr(msg, "name", None),
                "status":  "failed" if is_error else "success",
            })
            order += 1

    return steps


def _steps_from_details(step_details: list) -> List[Dict[str, Any]]:
    """Convert Phase 4 step_details into step dicts."""
    steps: List[Dict[str, Any]] = []
    for i, detail in enumerate(step_details):
        is_failed = detail.get("status") == "failed"
        content = detail.get("step", "")
        if detail.get("error"):
            content = f"{content}\nError: {detail['error']}"
        steps.append({
            "order":   i,
            "type":    "act",
            "content": content[:2000],
            "tool_name": None,
            "status":  "failed" if is_failed else "success",
            "error":   detail.get("error"),
        })
    return steps


def _extract_steps(messages: list) -> list:
    """Compat alias for testomat_service."""
    return _steps_from_messages(messages)


# ============================================================
# SCRIPT GENERATION (no run persistence)
# ============================================================

async def generate_script_v1(
    db: AsyncSession,
    test_case_id: str,
    app_url: Optional[str] = None,
    save_to_db: bool = True,
    dom_snapshot: Optional[str] = None,
    page_snapshots: Optional[Dict[str, str]] = None,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    logger.info(f"Generating Script v1 for test_case {test_case_id} (app_url={app_url})")
    await _push_event(test_case_id, "generation_started", {"test_case_id": test_case_id})

    test_case = await repo.get_test_case(db, test_case_id)
    if not test_case:
        error = f"TestCase {test_case_id} not found"
        await _push_event(test_case_id, "generation_failed", {"error": error})
        return {"status": "error", "error": error}

    test_cases = [{
        "title": test_case.title,
        "description": test_case.description,
        "risk_level": test_case.risk_level,
        "preconditions": test_case.preconditions,
        "postconditions": test_case.postconditions,
        "steps": test_case.steps,
        "gherkin_source": test_case.gherkin_source,
        "test_data": test_case.test_data,
        "expected_results": test_case.expected_results,
        "locators": test_case.locators,
    }]

    if dom_snapshot and not page_snapshots:
        page_snapshots = {"landing": dom_snapshot}

    if page_snapshots is None and app_url:
        page_snapshots = await _take_multipage_snapshot(
            app_url,
            steps=test_case.steps,
            gherkin_source=test_case.gherkin_source,
        )

    gen_result = await _script_generator.generate(
        test_cases,
        app_url=app_url,
        page_snapshots=page_snapshots if page_snapshots else None,
        model_id=model_id,
    )

    if gen_result.get("status") != "generated":
        await _push_event(test_case_id, "generation_failed", {"error": gen_result.get("error", "Generation failed")})
        return gen_result

    if save_to_db:
        script_version = await repo.save_script(
            db,
            test_case_id=test_case_id,
            script_content=gen_result["script_v1"],
            source=ScriptSource.V1_DRAFT,
            placeholder_count=gen_result["placeholder_count"],
            validation_status=ScriptValidationStatus.NOT_VALIDATED,
        )
        await repo.commit(db)

        gen_result["script_version_id"] = script_version.id
        gen_result["version_number"] = script_version.version_number

    await _push_event(test_case_id, "generation_completed", {
        "placeholder_count": gen_result["placeholder_count"],
        "script_version_id": gen_result.get("script_version_id"),
        "generation_mode": gen_result.get("generation_mode", "unknown"),
    })
    return gen_result


# ============================================================
# EXECUTION — single TC (wraps in a TestExecution of 1 TC)
# ============================================================

def _map_exec_status_to_tc_result_status(exec_status: str, steps_failed: int) -> TestCaseResultStatus:
    """Translate agent exec_result.execution_status into TestCaseResultStatus."""
    if exec_status in ("passed", "completed") and steps_failed == 0:
        return TestCaseResultStatus.PASSED
    if exec_status == "error":
        return TestCaseResultStatus.ERROR
    return TestCaseResultStatus.FAILED


async def execute_script(
    db: AsyncSession,
    test_case_id: str,
    script_version_id: Optional[str] = None,
    app_url: Optional[str] = None,
    browser: str = "chromium",
    headless: bool = True,
    save_to_db: bool = True,
    page_snapshots: Optional[Dict[str, str]] = None,
    model_id: Optional[str] = None,
    triggered_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute one TC. Creates a TestExecution wrapping a single TestCaseResult.
    """
    logger.info(f"Executing script for test_case {test_case_id}")

    # Script v1 is OPTIONAL — the ReAct agent runs directly from the test case.
    if script_version_id:
        script_version = await repo.get_script_version(db, script_version_id)
    else:
        script_version = await repo.get_active_script(db, test_case_id)

    script_hint = script_version.script_content if script_version else None

    test_case = await repo.get_test_case(db, test_case_id)
    if not test_case:
        return {"status": "error", "error": f"TestCase {test_case_id} not found"}

    suite_id = test_case.test_suite_id

    # Create the wrapping TestExecution + single TestCaseResult
    execution = None
    tc_result = None
    if save_to_db and suite_id:
        execution = await repo.create_test_execution(
            db,
            suite_id=suite_id,
            app_url=app_url or settings.TEST_APPLICATION_URL,
            browser=browser,
            headless=headless,
            stop_on_failure=False,
            model_id=model_id,
            triggered_by=triggered_by,
            total_count=1,
        )
        tc_result = await repo.create_tc_result(
            db,
            execution_id=execution.id,
            test_case_id=test_case_id,
            execution_order=1,
            script_version_id=script_version.id if script_version else None,
        )
        await repo.commit(db)

    await _push_event(test_case_id, "execution_started", {
        "test_case_id":  test_case_id,
        "execution_id":  execution.id if execution else None,
        "tc_result_id":  tc_result.id if tc_result else None,
    })

    await _push_event(test_case_id, "agent_step", {
        "step_type": "think",
        "tool": "system",
        "content": f"🚀 Starting execution — Browser: {browser} | Headless: {headless}",
        "status": "success",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    if app_url:
        await _push_event(test_case_id, "agent_step", {
            "step_type": "think",
            "tool": "system",
            "content": f"🎯 Target URL: {app_url}",
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def _on_step(label: str, status: str, error: str = None):
        await _push_event(test_case_id, "agent_step", {
            "step_type": "act",
            "tool": "playwright",
            "content": label,
            "status": "success" if status == "passed" else "failed",
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    tc_for_agent = {
        "title": test_case.title,
        "description": test_case.description,
        "preconditions": test_case.preconditions,
        "postconditions": test_case.postconditions,
        "steps": test_case.steps,
        "gherkin_source": test_case.gherkin_source,
        "test_data": test_case.test_data,
        "expected_results": test_case.expected_results,
        "locators": test_case.locators,
    }

    try:
        # Open one browser session and let the ReAct agent drive it from the test case
        async with PlaywrightMCPClient(headless=headless, browser=browser) as mcp:
            tools = {t.name: t for t in mcp.tools}
            exec_result = await _react_agent.run_react(
                tools,
                test_case=tc_for_agent,
                app_url=app_url or settings.TEST_APPLICATION_URL,
                test_case_id=test_case_id,
                on_step=_on_step,
                script_v1_hint=script_hint,
                model_id=model_id,
            )

        if save_to_db and tc_result and execution:
            await _persist_tc_result(
                db, tc_result.id, execution.id, script_version, exec_result,
                test_case_id=test_case_id,
            )

        # Testomat reporting (best-effort)
        from app.models.test_case import TestCase as _TC
        from app.services import testomat_service
        tc = await db.get(_TC, test_case_id)
        if tc:
            testomat_status = (
                "passed"
                if exec_result.get("execution_status") in ("passed", "completed")
                else "failed"
            )
            await testomat_service.report_execution(
                tc_code=tc.tc_code,
                title=tc.title,
                status=testomat_status,
                browser=browser,
                duration=exec_result.get("duration"),
                steps=_steps_from_messages(exec_result.get("raw_messages", [])),
                error_message=exec_result.get("error"),
            )

        exec_result["execution_id"]     = execution.id if execution else None
        exec_result["tc_result_id"]     = tc_result.id if tc_result else None
        exec_result["script_version_id"] = script_version.id if script_version else None

        await _push_event(test_case_id, "completed", {
            "execution_id":          exec_result["execution_id"],
            "tc_result_id":          exec_result["tc_result_id"],
            "execution_status":      exec_result.get("execution_status"),
            "steps_passed":          exec_result.get("steps_passed", 0),
            "steps_failed":          exec_result.get("steps_failed", 0),
            "remaining_placeholders": exec_result.get("remaining_placeholders", 0),
            "script_version_id":     exec_result["script_version_id"],
            "script_v2":             exec_result.get("script_v2"),
            "duration":              exec_result.get("duration", 0),
            "step_details":          exec_result.get("step_details", []),
        })

        return exec_result

    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)

        if save_to_db and execution:
            await repo.update_test_execution(
                db,
                execution_id=execution.id,
                status=TestExecutionStatus.ABORTED,
                completed_at=datetime.utcnow(),
                failed_count=1,
            )
            if tc_result:
                await repo.update_tc_result(
                    db,
                    tc_result_id=tc_result.id,
                    status=TestCaseResultStatus.ERROR,
                    error_message=str(e),
                    completed_at=datetime.utcnow(),
                )
            await repo.commit(db)

        await _push_event(test_case_id, "failed", {
            "error": str(e),
            "execution_id": execution.id if execution else None,
            "tc_result_id": tc_result.id if tc_result else None,
        })

        return {
            "status": "error",
            "error":  str(e),
            "execution_id":  execution.id if execution else None,
            "tc_result_id":  tc_result.id if tc_result else None,
        }


async def _persist_tc_result(
    db: AsyncSession,
    tc_result_id: str,
    execution_id: str,
    script_version: Any,
    exec_result: Dict[str, Any],
    test_case_id: Optional[str] = None,
) -> None:
    """Persist agent results into TestCaseResult + script_v2 logic + auto-defect.

    script_version may be None when the tester never generated a v1 draft and the
    ReAct agent ran directly from the test case. In that case test_case_id supplies
    the link and the reconstructed script_v2 becomes the first saved script.
    """
    steps_json = _build_steps_json(exec_result)
    steps_passed = int(exec_result.get("steps_passed", 0))
    steps_failed = int(exec_result.get("steps_failed", 0))
    duration     = exec_result.get("duration")

    # Resolve the owning test case id from whichever source is available
    tc_id = test_case_id or (script_version.test_case_id if script_version else None)

    # If the agent produced a script (ReAct always does), save v2 and pin it active
    script_v2_record = None
    if exec_result.get("script_v2") and tc_id:
        script_v2_record = await repo.save_script(
            db,
            test_case_id=tc_id,
            script_content=exec_result["script_v2"],
            source=ScriptSource.V2_CORRECTED,
            placeholder_count=exec_result.get("remaining_placeholders", 0),
            is_active=True,
        )
        await repo.commit(db)

        locator_mapping = exec_result.get("locator_mapping", {})
        await repo.update_test_case_after_execution(
            db,
            test_case_id=tc_id,
            active_script_id=script_v2_record.id,
            locator_mapping=locator_mapping,
        )
        await repo.commit(db)

    # Compute final TC result status
    tc_status = _map_exec_status_to_tc_result_status(
        exec_result.get("execution_status", "error"),
        steps_failed,
    )

    # Prefer the agent's own justification (ReAct verdict) when present
    remaining = exec_result.get("remaining_placeholders", 0)
    total_ph = (script_version.placeholder_count or 0) if script_version else 0
    resolved_ph = total_ph - remaining
    justification = (
        f"Steps: {steps_passed} passed, {steps_failed} failed."
        + (f" Placeholders: {resolved_ph}/{total_ph} resolved." if total_ph else "")
    )

    fallback_version_id = script_version.id if script_version else None
    await repo.update_tc_result(
        db,
        tc_result_id=tc_result_id,
        status=tc_status,
        steps=steps_json,
        steps_passed=steps_passed,
        steps_failed=steps_failed,
        justification=justification,
        error_message=exec_result.get("error"),
        screenshot_b64=exec_result.get("screenshot"),
        duration=duration,
        completed_at=datetime.utcnow(),
        script_version_id=(script_v2_record.id if script_v2_record else fallback_version_id),
    )

    # Update parent execution counters (single-TC mode)
    counter_updates: Dict[str, int] = {
        "passed_count":  1 if tc_status == TestCaseResultStatus.PASSED  else 0,
        "failed_count":  1 if tc_status == TestCaseResultStatus.FAILED  else 0,
        "error_count":   1 if tc_status == TestCaseResultStatus.ERROR   else 0,
        "skipped_count": 1 if tc_status == TestCaseResultStatus.SKIPPED else 0,
    }
    await repo.update_test_execution(
        db,
        execution_id=execution_id,
        status=TestExecutionStatus.COMPLETED,
        completed_at=datetime.utcnow(),
        duration=duration,
        **counter_updates,
    )
    await repo.commit(db)

    # Auto-defect on failure
    defect_tc_id = tc_id or (script_version.test_case_id if script_version else None)
    if tc_status in (TestCaseResultStatus.FAILED, TestCaseResultStatus.ERROR) and defect_tc_id:
        try:
            from app.services.execution_report_service import create_defect_from_execution
            await create_defect_from_execution(
                db, tc_result_id=tc_result_id,
                test_case_id=defect_tc_id,
            )
            await repo.commit(db)
        except Exception as e:
            logger.warning(f"Auto-defect creation failed (non-blocking): {e}")


async def run_full_workflow(
    db: AsyncSession,
    test_case_id: str,
    app_url: Optional[str] = None,
    browser: str = "chromium",
    headless: bool = True,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    logger.info(f"Starting full workflow for test_case {test_case_id}")

    page_snapshots: Dict[str, str] = {}
    if app_url:
        test_case = await repo.get_test_case(db, test_case_id)
        if test_case:
            page_snapshots = await _take_multipage_snapshot(
                app_url,
                steps=test_case.steps,
                gherkin_source=test_case.gherkin_source,
            )

    gen_result = await generate_script_v1(
        db,
        test_case_id=test_case_id,
        app_url=app_url,
        save_to_db=True,
        page_snapshots=page_snapshots or None,
        model_id=model_id,
    )

    if gen_result.get("status") != "generated":
        return {
            "workflow_status": "generation_failed",
            "generation": gen_result,
            "execution": None,
            "summary": {"error": gen_result.get("error", "Generation failed")}
        }

    exec_result = await execute_script(
        db,
        test_case_id=test_case_id,
        app_url=app_url,
        browser=browser,
        headless=headless,
        save_to_db=True,
        page_snapshots=page_snapshots or None,
        model_id=model_id,
    )

    total_steps = exec_result.get("steps_passed", 0) + exec_result.get("steps_failed", 0)
    success_rate = (
        (exec_result["steps_passed"] / total_steps * 100)
        if total_steps > 0 else 0
    )

    return {
        "workflow_status": "completed" if exec_result.get("execution_status") != "error" else "execution_failed",
        "generation": {
            "status": gen_result["status"],
            "placeholder_count": gen_result["placeholder_count"],
            "script_version_id": gen_result.get("script_version_id"),
        },
        "execution": {
            "status": exec_result.get("execution_status"),
            "steps_passed": exec_result.get("steps_passed", 0),
            "steps_failed": exec_result.get("steps_failed", 0),
            "remaining_placeholders": exec_result.get("remaining_placeholders", 0),
            "execution_id": exec_result.get("execution_id"),
            "tc_result_id": exec_result.get("tc_result_id"),
            "script_version_id": exec_result.get("script_version_id"),
        },
        "summary": {
            "total_steps": total_steps,
            "passed_steps": exec_result.get("steps_passed", 0),
            "failed_steps": exec_result.get("steps_failed", 0),
            "success_rate": round(success_rate, 2),
        },
    }


# ============================================================
# READ-SIDE HELPERS
# ============================================================

async def get_test_case_scripts(db: AsyncSession, test_case_id: str) -> Dict[str, Any]:
    scripts = await repo.get_all_scripts(db, test_case_id)
    active_script = await repo.get_active_script(db, test_case_id)
    return {
        "test_case_id": test_case_id,
        "active_script_id": active_script.id if active_script else None,
        "scripts": [
            {
                "id": s.id,
                "version_number": s.version_number,
                "source": s.source.value,
                "is_active": s.is_active,
                "placeholder_count": s.placeholder_count,
                "validation_status": s.validation_status.value,
                "created_at": s.created_at.isoformat(),
            }
            for s in scripts
        ],
    }


async def get_tc_result_details(db: AsyncSession, tc_result_id: str) -> Dict[str, Any]:
    """Détails complets d'un TestCaseResult (pour la page View Details)."""
    tc_result = await repo.get_tc_result(db, tc_result_id)
    if not tc_result:
        return {"error": f"TestCaseResult {tc_result_id} not found"}

    execution = await repo.get_test_execution(db, tc_result.execution_id)

    return {
        "tc_result": {
            "id":             tc_result.id,
            "execution_id":   tc_result.execution_id,
            "test_case_id":   tc_result.test_case_id,
            "execution_order": tc_result.execution_order,
            "status":         tc_result.status.value,
            "steps":          tc_result.steps or [],
            "steps_passed":   tc_result.steps_passed,
            "steps_failed":   tc_result.steps_failed,
            "justification":  tc_result.justification,
            "error_message":  tc_result.error_message,
            "screenshot_b64": tc_result.screenshot_b64,
            "duration":       tc_result.duration,
            "started_at":     tc_result.started_at.isoformat() if tc_result.started_at else None,
            "completed_at":   tc_result.completed_at.isoformat() if tc_result.completed_at else None,
        },
        "execution": {
            "id":         execution.id,
            "browser":    execution.browser,
            "app_url":    execution.app_url,
            "headless":   execution.headless,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
        } if execution else None,
    }


# ============================================================
# SUITE EXECUTION — TWO-PHASE (creates TestExecution + per-TC results)
# ============================================================

async def run_suite_smart(
    db: AsyncSession,
    suite_id: str,
    app_url: Optional[str] = None,
    browser: str = "chromium",
    headless: bool = True,
    stop_on_failure: bool = False,
    model_id: Optional[str] = None,
    triggered_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Two-phase optimised suite execution.

    Phase 1 — parallel script generation (sem=3) for TCs missing scripts.
    Phase 2 — single shared browser session executes each TC sequentially.

    Persists everything in ONE TestExecution + N TestCaseResult rows.
    """
    from sqlalchemy import select as _select
    from app.models.test_case import TestCase as _TC
    from app.models.test_suite import TestSuite as _TS
    from app.core.database import async_session_maker

    channel = f"suite_{suite_id}"

    # ── Load suite + TCs ────────────────────────────────────────────────────
    tc_rows = (await db.execute(
        _select(_TC)
        .where(
            _TC.test_suite_id == suite_id,
            _TC.is_active == True,
            _TC.excluded_from_run == False,
        )
        .order_by(_TC.execution_order.asc().nullslast(), _TC.tc_code.asc())
    )).scalars().all()

    suite_row = await db.get(_TS, suite_id)
    suite_title = suite_row.title if suite_row else suite_id

    if not tc_rows:
        await _push_event(channel, "completed", {
            "suite_id": suite_id, "suite_status": "completed",
            "message": "No active test cases in suite",
            "passed": 0, "failed": 0, "skipped": 0, "total": 0, "results": [],
        })
        return {"suite_status": "completed", "total": 0}

    logger.info(f"Suite smart run: '{suite_title}' — {len(tc_rows)} TCs, app_url={app_url}")

    # ── Create wrapping TestExecution ───────────────────────────────────────
    execution = await repo.create_test_execution(
        db,
        suite_id=suite_id,
        app_url=app_url or settings.TEST_APPLICATION_URL,
        browser=browser,
        headless=headless,
        stop_on_failure=stop_on_failure,
        model_id=model_id,
        triggered_by=triggered_by,
        total_count=len(tc_rows),
    )

    # Pre-create TestCaseResult rows so the UI can show "pending"
    tc_result_by_id: Dict[str, Any] = {}
    for idx, tc in enumerate(tc_rows):
        tcr = await repo.create_tc_result(
            db,
            execution_id=execution.id,
            test_case_id=tc.id,
            execution_order=idx + 1,
            script_version_id=None,
        )
        tc_result_by_id[tc.id] = tcr
    await repo.commit(db)

    await _push_event(channel, "suite_started", {
        "suite_id":       suite_id,
        "suite_title":    suite_title,
        "execution_id":   execution.id,
        "test_case_ids":  [tc.id for tc in tc_rows],
        "total":          len(tc_rows),
        "app_url":        app_url,
    })

    # ── Phase 1 — parallel generation ───────────────────────────────────────
    shared_snapshots: Dict[str, str] = {}
    tcs_needing_scripts: List[Any] = []
    for tc in tc_rows:
        if not await repo.get_active_script(db, tc.id):
            tcs_needing_scripts.append(tc)

    if tcs_needing_scripts:
        logger.info(f"Phase 1: {len(tcs_needing_scripts)} TCs need scripts")
        await _push_event(channel, "tc_event", {
            "test_case_id": suite_id,
            "type": "phase1",
            "message": f"Generating {len(tcs_needing_scripts)} missing scripts in parallel…",
        })

        if app_url:
            all_steps: list = []
            all_gherkin_parts: list = []
            for tc in tcs_needing_scripts:
                if tc.steps:
                    all_steps.extend(tc.steps)
                if tc.gherkin_source:
                    all_gherkin_parts.append(tc.gherkin_source)
            shared_snapshots = await _take_multipage_snapshot(
                app_url,
                steps=all_steps,
                gherkin_source="\n".join(all_gherkin_parts) if all_gherkin_parts else None,
            )

        _gen_sem = asyncio.Semaphore(3)

        async def _gen_one(tc) -> None:
            async with _gen_sem:
                async with async_session_maker() as session:
                    try:
                        result = await generate_script_v1(
                            session, tc.id,
                            app_url=app_url,
                            save_to_db=True,
                            page_snapshots=shared_snapshots or None,
                            model_id=model_id,
                        )
                        msg_type = "generated" if result.get("status") == "generated" else "gen_failed"
                        msg = (
                            f"Script generated ({result.get('placeholder_count', 0)} placeholders)"
                            if result.get("status") == "generated"
                            else f"Generation failed: {result.get('error')}"
                        )
                    except Exception as e:
                        msg_type, msg = "gen_failed", f"Generation error: {e}"
                        logger.error(f"Phase 1 gen error for {tc.tc_code}: {e}")
                    await _push_event(channel, "tc_event", {
                        "test_case_id": tc.id, "type": msg_type, "message": msg,
                    })

        await asyncio.gather(*[_gen_one(tc) for tc in tcs_needing_scripts], return_exceptions=True)
        logger.info("Phase 1 done")

    # ── Phase 2 — single shared browser session ─────────────────────────────
    results: List[Dict[str, Any]] = []
    passed = failed = skipped = error_count = 0
    started = datetime.utcnow()

    def _is_auth_tc(title: str, script_content: str) -> bool:
        kws = ("login", "sign in", "signin", "log in", "authenticate", "auth")
        if any(kw in title.lower() for kw in kws):
            return True
        sc = (script_content or "").lower()
        return "password" in sc and ".fill(" in sc

    _saved_local_storage: Optional[str] = None

    async def _save_local_storage(tools: dict) -> Optional[str]:
        if "browser_evaluate" not in tools:
            return None
        try:
            raw = await tools["browser_evaluate"].ainvoke({
                "expression": "JSON.stringify(Object.fromEntries(Object.entries(localStorage)))"
            })
            result = str(raw).strip()
            if result and result != "{}":
                logger.info(f"Suite: localStorage saved ({len(result)} chars)")
                return result
        except Exception as e:
            logger.warning(f"Suite: localStorage save failed: {e}")
        return None

    async def _restore_local_storage(tools: dict, saved: str) -> None:
        if "browser_evaluate" not in tools or not saved:
            return
        try:
            inject = (
                "(function(d){"
                "try{var o=JSON.parse(d);"
                "Object.keys(o).forEach(function(k){localStorage.setItem(k,o[k]);});"
                "}catch(e){}"
                "})('" + saved.replace("'", "\\'") + "')"
            )
            await tools["browser_evaluate"].ainvoke({"expression": inject})
            logger.info("Suite: localStorage restored")
        except Exception as e:
            logger.warning(f"Suite: localStorage restore failed: {e}")

    async with PlaywrightMCPClient(headless=headless, browser=browser) as mcp:
        tools = {t.name: t for t in mcp.tools}

        if app_url and "browser_navigate" in tools:
            try:
                await tools["browser_navigate"].ainvoke({"url": app_url})
                await asyncio.sleep(1.5)
            except Exception as warm_e:
                logger.warning(f"Browser warm-up navigate failed: {warm_e}")

        for idx, tc in enumerate(tc_rows):
            tc_id = tc.id
            tcr   = tc_result_by_id[tc_id]

            await _push_event(channel, "tc_started", {
                "index": idx + 1,
                "total": len(tc_rows),
                "tc_id": tc_id,
                "tc_code": tc.tc_code,
                "title": tc.title,
                "tc_result_id": tcr.id,
            })

            # Script v1 is now OPTIONAL — the ReAct agent works directly from the
            # test case and reads the live DOM. If a draft exists, it's passed as a hint.
            active_script = await repo.get_active_script(db, tc_id)
            script_hint = active_script.script_content if active_script else None

            # Inter-TC: don't navigate to app_url; restore localStorage for non-auth TCs
            if idx > 0:
                await asyncio.sleep(0.5)
                if _saved_local_storage and not _is_auth_tc(tc.title, script_hint or ""):
                    await _restore_local_storage(tools, _saved_local_storage)

            async def _on_step(label: str, status: str, error: str = None, _tc_id=tc_id):
                await _push_event(_tc_id, "agent_step", {
                    "step_type": "act",
                    "tool": "playwright",
                    "content": label,
                    "status": "success" if status == "passed" else "failed",
                    "error": error,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            tc_for_agent = {
                "title": tc.title,
                "description": tc.description,
                "preconditions": tc.preconditions,
                "postconditions": tc.postconditions,
                "steps": tc.steps,
                "gherkin_source": tc.gherkin_source,
                "test_data": tc.test_data,
                "expected_results": tc.expected_results,
                "locators": tc.locators,
            }

            try:
                exec_result = await asyncio.wait_for(
                    _react_agent.run_react(
                        tools,
                        test_case=tc_for_agent,
                        app_url=app_url or settings.TEST_APPLICATION_URL,
                        test_case_id=tc_id,
                        on_step=_on_step,
                        script_v1_hint=script_hint,
                        suite_continuation=(idx > 0),
                        model_id=model_id,
                    ),
                    timeout=240.0,
                )
            except asyncio.TimeoutError:
                logger.warning(f"TC {tc.tc_code} timed out after 180 s")
                exec_result = {
                    "execution_status": "error",
                    "error": "Timed out after 180 s",
                    "steps_passed": 0, "steps_failed": 0,
                    "step_details": [], "duration": 180.0,
                    "remaining_placeholders": 0,
                }
            except Exception as exec_e:
                logger.error(f"TC {tc.tc_code} execution error: {exec_e}", exc_info=True)
                exec_result = {
                    "execution_status": "error",
                    "error": str(exec_e),
                    "steps_passed": 0, "steps_failed": 0,
                    "step_details": [], "duration": 0.0,
                    "remaining_placeholders": 0,
                }

            try:
                await _persist_tc_result(
                    db, tcr.id, execution.id, active_script, exec_result, test_case_id=tc_id,
                )
            except Exception as save_e:
                logger.error(f"Failed to save results for {tc.tc_code}: {save_e}")

            # Capture localStorage for downstream TCs
            if exec_result.get("execution_status") in ("passed", "completed"):
                if _is_auth_tc(tc.title, script_hint or ""):
                    captured = await _save_local_storage(tools)
                    if captured:
                        _saved_local_storage = captured

            raw_exec_status = exec_result.get("execution_status", "error")
            steps_failed_count = exec_result.get("steps_failed", 0)
            if raw_exec_status in ("passed", "completed") and steps_failed_count == 0:
                status = "passed"
                passed += 1
            elif raw_exec_status == "error":
                status = "error"
                error_count += 1
                failed += 1
            else:
                status = "failed"
                failed += 1

            tc_result_payload = {
                "tc_id":         tc_id, "tc_code": tc.tc_code, "title": tc.title,
                "status":        status,
                "tc_result_id":  tcr.id,
                "steps_passed":  exec_result.get("steps_passed", 0),
                "steps_failed":  exec_result.get("steps_failed", 0),
                "duration":      round(exec_result.get("duration", 0) or 0, 1),
                "error":         exec_result.get("error"),
            }
            results.append(tc_result_payload)
            await _push_event(channel, "tc_completed", tc_result_payload)

            if failed > 0 and stop_on_failure:
                for rem_tc in tc_rows[idx + 1:]:
                    skipped += 1
                    rem_tcr = tc_result_by_id[rem_tc.id]
                    await repo.update_tc_result(
                        db,
                        tc_result_id=rem_tcr.id,
                        status=TestCaseResultStatus.SKIPPED,
                        error_message="Skipped — previous TC failed",
                        completed_at=datetime.utcnow(),
                    )
                    skip_payload = {
                        "tc_id": rem_tc.id, "tc_code": rem_tc.tc_code,
                        "title": rem_tc.title, "status": "skipped",
                        "tc_result_id": rem_tcr.id,
                        "steps_passed": 0, "steps_failed": 0,
                        "duration": 0, "error": "Skipped — previous TC failed",
                    }
                    results.append(skip_payload)
                    await _push_event(channel, "tc_completed", skip_payload)
                await repo.commit(db)
                break

    # ── Finalize execution ──────────────────────────────────────────────────
    total = len(tc_rows)
    suite_status = "passed" if failed == 0 and skipped == 0 else ("partial" if passed > 0 else "failed")
    success_rate = round((passed / total * 100) if total > 0 else 0, 1)
    total_duration = round((datetime.utcnow() - started).total_seconds(), 1)

    await repo.update_test_execution(
        db,
        execution_id=execution.id,
        status=TestExecutionStatus.COMPLETED,
        completed_at=datetime.utcnow(),
        duration=total_duration,
        passed_count=passed,
        failed_count=failed - error_count,
        error_count=error_count,
        skipped_count=skipped,
    )
    await repo.commit(db)

    logger.info(f"Suite smart done: {passed} passed, {failed} failed, {skipped} skipped / {total}")

    await _push_event(channel, "completed", {
        "suite_id":      suite_id,
        "execution_id":  execution.id,
        "suite_status":  suite_status,
        "total":         total,
        "passed":        passed,
        "failed":        failed,
        "skipped":       skipped,
        "success_rate":  success_rate,
        "duration":      total_duration,
        "results":       results,
    })

    return {
        "suite_status": suite_status,
        "execution_id": execution.id,
        "total": total, "passed": passed, "failed": failed,
        "skipped": skipped, "success_rate": success_rate, "results": results,
    }


# ============================================================
# SSE push wrapper
# ============================================================

async def _push_event(test_case_id: str, event_type: str, data: Dict[str, Any]) -> None:
    """Push event to SSE manager."""
    try:
        from app.streaming.sse_manager import push_event
        from app.ai_agents_v2.playwright_e2e.agent import format_tool_result

        if event_type == "agent_step" and "tool" in data:
            tool_name = data.get("tool", "")
            content = data.get("content", "")
            if data.get("step_type") == "observe":
                formatted_content = format_tool_result(tool_name, content)
                data["content"] = formatted_content

        await push_event(test_case_id, event_type, data)
    except ImportError as e:
        logger.warning(f"SSE manager not available, event not sent: {event_type} - {e}")
