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
    TestRunStatus, TestResultStatus, StepType, StepStatus
)

logger = logging.getLogger(__name__)

# Initialisation des agents (globale)
_script_generator = get_script_generator()
_react_agent = PlaywrightReActAgent()
_agent_instance = PlaywrightReActAgent()

# ============================================================
# PRE-FLIGHT HELPERS — multi-page snapshot capture
# ============================================================

# Accessibility-tree element types considered navigational
_NAV_ELEMENT_PATTERNS = [
    _re.compile(r'link\s+"([^"]{2,40})"\s+\[ref=(e\d+)\]', _re.IGNORECASE),
    _re.compile(r'menuitem\s+"([^"]{2,40})"\s+\[ref=(e\d+)\]', _re.IGNORECASE),
    _re.compile(r'tab\s+"([^"]{2,40})"\s+\[ref=(e\d+)\]', _re.IGNORECASE),
]

# Words that should never be treated as page keywords
_STOP_WORDS = frozenset({
    "the", "and", "that", "this", "with", "for", "from", "click", "then",
    "when", "given", "have", "should", "user", "button", "form", "field",
    "enter", "fill", "type", "select", "verify", "assert", "check",
})


def _extract_nav_keywords(
    steps: Optional[list] = None,
    gherkin_source: Optional[str] = None,
) -> frozenset:
    """
    Derive navigation-target page names from test case steps / Gherkin text.
    Returns a frozenset of lowercase keywords (e.g. {'dashboard', 'users'}).
    """
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

    # Pattern 1 — explicit navigation verbs followed by a destination
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

    # Pattern 2 — "on/from the X page/section" references
    page_ref_re = _re.compile(
        r'(?:on|from|in)\s+(?:the\s+)?([a-z][a-z\s]{2,20}?)\s+'
        r'(?:page|screen|section|tab|dashboard)',
        _re.IGNORECASE,
    )
    for m in page_ref_re.finditer(raw_text):
        kw = m.group(1).strip()
        if 2 < len(kw) < 30 and kw not in _STOP_WORDS:
            keywords.add(kw)

    # Pattern 3 — well-known SPA page names appearing anywhere in the text
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
    """
    Extract clickable navigation elements from a raw accessibility-tree snapshot.
    Returns [(display_text, ref_id), ...] — duplicates removed, URLs excluded.
    """
    links: List[tuple] = []
    seen: set = set()
    for pattern in _NAV_ELEMENT_PATTERNS:
        for m in pattern.finditer(snapshot_text):
            text = m.group(1).strip()
            ref = m.group(2)
            text_lower = text.lower()
            if text_lower in seen:
                continue
            # Skip entries that look like URL fragments
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
    """
    Pre-flight multi-page DOM capture.

    Opens ONE browser session and captures:
      - The landing page DOM (always)
      - Up to `max_extra_pages` additional pages identified from test steps

    Navigation to sub-pages is done by clicking matching links found in the
    landing accessibility tree — no URL guessing.

    Returns { page_label: compressed_snapshot } or {} on total failure.
    """
    try:
        nav_keywords = _extract_nav_keywords(steps, gherkin_source)
        logger.info(f"Pre-flight: app_url={app_url}, keywords={nav_keywords or 'none'}")

        async with PlaywrightMCPClient(headless=True, browser="chromium") as mcp:
            tools = {t.name: t for t in mcp.tools}
            required = {"browser_navigate", "browser_snapshot"}
            if not required.issubset(tools):
                logger.warning("Pre-flight: required MCP tools not available — skipping")
                return {}

            # ── Landing page ──────────────────────────────────────────────────
            await tools["browser_navigate"].ainvoke({"url": app_url})
            await asyncio.sleep(2.0)
            raw = str(await tools["browser_snapshot"].ainvoke({}))
            landing_text = _agent_instance._extract_snapshot_text(raw)
            snapshots: Dict[str, str] = {"landing": _compress_dom(landing_text)}
            logger.info(f"Pre-flight: landing snapshot captured ({len(snapshots['landing'])} chars)")

            if not nav_keywords or max_extra_pages <= 0 or "browser_click" not in tools:
                return snapshots

            # ── Additional pages via nav-link clicks ──────────────────────────
            nav_links = _parse_nav_links(landing_text)
            logger.info(f"Pre-flight: {len(nav_links)} nav links found in landing DOM")

            visited: set = set()
            extra_count = 0

            for link_text, link_ref in nav_links:
                if extra_count >= max_extra_pages:
                    break
                link_lower = link_text.lower().strip()
                # Match link against any extracted keyword
                if not any(kw in link_lower or link_lower in kw for kw in nav_keywords):
                    continue
                if link_lower in visited:
                    continue

                visited.add(link_lower)
                try:
                    await tools["browser_click"].ainvoke(
                        {"element": link_text, "ref": link_ref}
                    )
                    await asyncio.sleep(1.5)
                    raw2 = str(await tools["browser_snapshot"].ainvoke({}))
                    page_text = _agent_instance._extract_snapshot_text(raw2)
                    label = link_lower.replace(" ", "_")
                    snapshots[label] = _compress_dom(page_text)
                    extra_count += 1
                    logger.info(
                        f"Pre-flight: captured '{label}' ({len(snapshots[label])} chars)"
                    )
                    # Return to landing for next iteration
                    await tools["browser_navigate"].ainvoke({"url": app_url})
                    await asyncio.sleep(1.0)
                except Exception as click_err:
                    logger.warning(f"Pre-flight: click on '{link_text}' failed: {click_err}")
                    try:
                        await tools["browser_navigate"].ainvoke({"url": app_url})
                        await asyncio.sleep(1.0)
                    except Exception:
                        pass

        logger.info(
            f"Pre-flight complete: {len(snapshots)} snapshot(s) captured — "
            f"{list(snapshots.keys())}"
        )
        return snapshots

    except Exception as e:
        logger.warning(f"Pre-flight multi-page snapshot failed — blind generation: {e}")
        return {}


# ============================================================
# SCRIPT VERSIONS
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
    """
    Generate a v1 Playwright script from a TestCase in the DB.

    Snapshot resolution priority:
      1. page_snapshots (pre-captured multi-page dict) — best quality, fewest placeholders
      2. dom_snapshot (legacy single-page str) — merged into page_snapshots["landing"]
      3. app_url provided but no snapshots → trigger pre-flight multi-page capture
      4. Nothing → blind generation (all placeholders)
    """
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

    # Normalise legacy single snapshot
    if dom_snapshot and not page_snapshots:
        page_snapshots = {"landing": dom_snapshot}

    # Pre-flight: capture multi-page snapshots when we have a URL but no snapshots yet
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
) -> Dict[str, Any]:
    """
    Exécute un script avec le ReAct Agent.
    """
    logger.info(f"Executing script for test_case {test_case_id}")
    
    if script_version_id:
        script_version = await repo.get_script_version(db, script_version_id)
    else:
        script_version = await repo.get_active_script(db, test_case_id)
    
    if not script_version:
        return {
            "status": "error",
            "error": f"No script found for test_case {test_case_id}"
        }
    
    test_run = None
    if save_to_db:
        test_run = await repo.create_test_run(
            db,
            script_version_id=script_version.id,
            base_url=app_url or settings.TEST_APPLICATION_URL,
            browser=browser,
            headless=headless
        )
        await repo.commit(db)
    
    await _push_event(test_case_id, "execution_started", {
        "test_case_id": test_case_id,
        "test_run_id": test_run.id if test_run else None,
    })

    # Publish the "banner" step so the terminal shows something immediately
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

    try:
        exec_result = await _react_agent.run(
            script_v1=script_version.script_content,
            **({"app_url": app_url} if app_url else {}),
            test_case_id=test_case_id,
            headless=headless,
            browser=browser,
            on_step=_on_step,
            page_snapshots=page_snapshots or {},
            model_id=model_id,
        )

        if save_to_db and test_run:
            await _save_execution_results(
                db,
                test_run_id=test_run.id,
                script_version=script_version,
                exec_result=exec_result
            )

        # Report to Testomat.io (best-effort, never blocks the main flow)
        from app.models.test_case import TestCase
        from app.services import testomat_service
        tc = await db.get(TestCase, script_version.test_case_id)
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
                steps=_extract_steps(exec_result.get("raw_messages", [])),
                error_message=exec_result.get("error"),
            )

        exec_result["test_run_id"] = test_run.id if test_run else None
        exec_result["script_version_id"] = script_version.id

        await _push_event(test_case_id, "completed", {
            "test_run_id": exec_result["test_run_id"],
            "execution_status": exec_result.get("execution_status"),
            "steps_passed": exec_result.get("steps_passed", 0),
            "steps_failed": exec_result.get("steps_failed", 0),
            "remaining_placeholders": exec_result.get("remaining_placeholders", 0),
            "script_version_id": exec_result["script_version_id"],
            "script_v2": exec_result.get("script_v2"),
            "duration": exec_result.get("duration", 0),
            "step_details": exec_result.get("step_details", []),
        })

        return exec_result

    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)

        if save_to_db and test_run:
            await repo.update_test_run(
                db,
                test_run_id=test_run.id,
                status=TestRunStatus.FAILED
            )
            await repo.commit(db)

        await _push_event(test_case_id, "failed", {
            "error": str(e),
            "test_run_id": test_run.id if test_run else None,
        })

        return {
            "status": "error",
            "error": str(e),
            "test_run_id": test_run.id if test_run else None
        }


def _extract_text_from_content(content) -> str:
    """Extract plain text from LangChain message content (str or list-of-dicts)."""
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


def _extract_steps(messages: list) -> list:
    """Parse LangGraph messages into step dicts."""
    steps = []
    order = 0
    for msg in messages:
        msg_type = type(msg).__name__

        if msg_type == "AIMessage":
            content = msg.content if isinstance(msg.content, str) else ""
            if content.strip():
                steps.append({
                    "step_order": order,
                    "step_type": StepType.THINK,
                    "content": content[:2000],
                    "status": StepStatus.SUCCESS,
                })
                order += 1

            tool_calls = getattr(msg, "tool_calls", None) or []
            for tc in tool_calls:
                args = tc.get("args", {})
                args_parts = [f"{k}={str(v)[:80]!r}" for k, v in args.items()]
                content_str = f"{tc.get('name', 'unknown')}({', '.join(args_parts)})"
                steps.append({
                    "step_order": order,
                    "step_type": StepType.ACT,
                    "content": content_str[:2000],
                    "tool_name": tc.get("name"),
                    "status": StepStatus.SUCCESS,
                })
                order += 1

        elif msg_type == "ToolMessage":
            text_content = _extract_text_from_content(msg.content)
            error_keywords = ("### error", "timeouterror", "exception", "unable to", "tool error (recoverable)")
            is_error = any(kw in text_content.lower() for kw in error_keywords)
            steps.append({
                "step_order": order,
                "step_type": StepType.OBSERVE,
                "content": text_content[:2000],
                "tool_name": getattr(msg, "name", None),
                "status": StepStatus.FAILED if is_error else StepStatus.SUCCESS,
            })
            order += 1

    return steps


def _extract_steps_from_details(step_details: list) -> list:
    """Convert Phase 4 step_details into DB-compatible step records."""
    steps = []
    for i, detail in enumerate(step_details):
        is_failed = detail.get("status") == "failed"
        content = detail.get("step", "")
        if detail.get("error"):
            content = f"{content}\nError: {detail['error']}"
        steps.append({
            "step_order": i,
            "step_type": StepType.ACT,
            "content": content[:2000],
            "status": StepStatus.FAILED if is_failed else StepStatus.SUCCESS,
        })
    return steps


async def _save_execution_results(
    db: AsyncSession,
    test_run_id: str,
    script_version: Any,
    exec_result: Dict[str, Any]
) -> None:
    """Sauvegarde les résultats d'exécution en base."""
    
    final_status = (
        TestRunStatus.COMPLETED 
        if exec_result.get("execution_status") in ["passed", "completed"]
        else TestRunStatus.FAILED
    )
    await repo.update_test_run(
        db,
        test_run_id=test_run_id,
        status=final_status,
        duration=exec_result.get("duration")
    )
    
    script_v2_record = None
    if exec_result.get("script_v2"):
        script_v2_record = await repo.save_script(
            db,
            test_case_id=script_version.test_case_id,
            script_content=exec_result["script_v2"],
            source=ScriptSource.V2_CORRECTED,
            placeholder_count=exec_result.get("remaining_placeholders", 0),
            is_active=True
        )
        await repo.commit(db)

        # Pin active script + persist discovered locators on the TestCase
        locator_mapping = exec_result.get("locator_mapping", {})
        await repo.update_test_case_after_execution(
            db,
            test_case_id=script_version.test_case_id,
            active_script_id=script_v2_record.id,
            locator_mapping=locator_mapping,
        )
        await repo.commit(db)
    
    raw_messages = exec_result.get("raw_messages", [])
    if raw_messages:
        steps = _extract_steps(raw_messages)
        if steps:
            await repo.add_steps_batch(db, test_run_id, steps)
    else:
        step_details = exec_result.get("step_details", [])
        if step_details:
            steps = _extract_steps_from_details(step_details)
            if steps:
                await repo.add_steps_batch(db, test_run_id, steps)

    execution_status = exec_result.get("execution_status", "")
    steps_failed = exec_result.get("steps_failed", 0)
    steps_passed = exec_result.get("steps_passed", 0)
    # "completed" with no failures → PASSED
    # "partial" or any step failure → FAILED (assertions missing or failing)
    # "error" (agent couldn't run at all) → ERROR
    if execution_status in ("passed", "completed") and steps_failed == 0:
        test_result_status = TestResultStatus.PASSED
    elif execution_status == "error":
        test_result_status = TestResultStatus.ERROR
    else:
        test_result_status = TestResultStatus.FAILED

    remaining = exec_result.get("remaining_placeholders", 0)
    total_ph = script_version.placeholder_count or 0
    resolved_ph = total_ph - remaining
    justification = (
        f"Placeholders: {resolved_ph}/{total_ph} resolved. "
        f"Steps: {steps_passed} passed, {steps_failed} failed."
    )
    await repo.save_test_result(
        db,
        test_run_id=test_run_id,
        status=test_result_status,
        justification=justification,
        step_count=steps_passed + steps_failed,
        screenshot_b64=exec_result.get("screenshot"),
    )
    
    await repo.commit(db)

    # ── Auto-create defect if execution failed ────────────────────────────────
    if final_status == TestRunStatus.FAILED:
        try:
            from app.services.execution_report_service import create_defect_from_execution
            tc_id = script_version.test_case_id
            await create_defect_from_execution(db, test_run_id=test_run_id, test_case_id=tc_id)
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
    """
    Full workflow: pre-flight snapshot → generation → execution.
    Snapshots are captured once and reused at both phases to avoid duplicate
    browser launches and redundant LLM DOM-resolution calls at runtime.
    """
    logger.info(f"Starting full workflow for test_case {test_case_id}")

    # Pre-flight: capture multi-page snapshots once for reuse across both phases
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
            "script_version_id": gen_result.get("script_version_id")
        },
        "execution": {
            "status": exec_result.get("execution_status"),
            "steps_passed": exec_result.get("steps_passed", 0),
            "steps_failed": exec_result.get("steps_failed", 0),
            "remaining_placeholders": exec_result.get("remaining_placeholders", 0),
            "test_run_id": exec_result.get("test_run_id"),
            "script_version_id": exec_result.get("script_version_id")
        },
        "summary": {
            "total_steps": total_steps,
            "passed_steps": exec_result.get("steps_passed", 0),
            "failed_steps": exec_result.get("steps_failed", 0),
            "success_rate": round(success_rate, 2)
        }
    }


async def get_test_case_scripts(
    db: AsyncSession,
    test_case_id: str
) -> Dict[str, Any]:
    """Récupère tous les scripts d'un test case."""
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
                "created_at": s.created_at.isoformat()
            }
            for s in scripts
        ]
    }


async def get_test_run_details(
    db: AsyncSession,
    test_run_id: str
) -> Dict[str, Any]:
    """Récupère les détails complets d'un test run."""
    test_run = await repo.get_test_run(db, test_run_id)
    if not test_run:
        return {"error": f"TestRun {test_run_id} not found"}
    
    steps = await repo.get_steps(db, test_run_id)
    test_result = await repo.get_test_result(db, test_run_id)
    
    return {
        "test_run": {
            "id": test_run.id,
            "status": test_run.status.value,
            "browser": test_run.browser,
            "headless": test_run.headless,
            "started_at": test_run.started_at.isoformat(),
            "completed_at": test_run.completed_at.isoformat() if test_run.completed_at else None,
            "duration": test_run.duration
        },
        "result": {
            "status": test_result.status.value if test_result else None,
            "justification": test_result.justification if test_result else None,
            "error_message": test_result.error_message if test_result else None
        } if test_result else None,
        "steps": [
            {
                "order": s.step_order,
                "type": s.step_type.value,
                "content": s.content,
                "tool_name": s.tool_name,
                "status": s.status.value,
                "duration": s.duration
            }
            for s in steps
        ]
    }

async def run_suite(
    db: AsyncSession,
    test_case_ids: List[str],
    app_url: Optional[str] = None,
    browser: str = "chromium",
    headless: bool = True,
    stop_on_failure: bool = False,
) -> Dict[str, Any]:
    """
    Execute multiple test cases sequentially, respecting execution order.
    Each TC pushes events to its own SSE channel.
    Returns a summary of all runs.
    """
    logger.info(f"Starting suite run: {len(test_case_ids)} test cases, stop_on_failure={stop_on_failure}")

    results = []
    passed = 0
    failed = 0
    skipped = 0

    for idx, tc_id in enumerate(test_case_ids):
        logger.info(f"Suite run: executing TC {idx + 1}/{len(test_case_ids)} — {tc_id}")

        await _push_event(tc_id, "suite_step", {
            "index": idx + 1,
            "total": len(test_case_ids),
            "test_case_id": tc_id,
            "message": f"Running test {idx + 1}/{len(test_case_ids)}",
        })

        try:
            exec_result = await execute_script(
                db,
                test_case_id=tc_id,
                app_url=app_url,
                browser=browser,
                headless=headless,
                save_to_db=True,
            )

            raw_exec_status = exec_result.get("execution_status", "error")
            steps_failed_count = exec_result.get("steps_failed", 0)
            if raw_exec_status in ("passed", "completed") and steps_failed_count == 0:
                status = "passed"
            elif raw_exec_status == "error":
                status = "error"
            else:
                status = "failed"

            results.append({
                "test_case_id": tc_id,
                "status": status,
                "test_run_id": exec_result.get("test_run_id"),
                "duration": exec_result.get("duration", 0),
                "error": exec_result.get("error"),
            })

            if status == "passed":
                passed += 1
            else:
                failed += 1
                if stop_on_failure:
                    logger.info(f"Suite run: stopping after failure on TC {tc_id}")
                    # Mark remaining as skipped
                    for remaining_id in test_case_ids[idx + 1:]:
                        skipped += 1
                        results.append({
                            "test_case_id": remaining_id,
                            "status": "skipped",
                            "test_run_id": None,
                            "duration": 0,
                            "error": "Skipped due to previous failure",
                        })
                    break

        except Exception as e:
            logger.error(f"Suite run: TC {tc_id} failed with exception: {e}")
            failed += 1
            results.append({
                "test_case_id": tc_id,
                "status": "error",
                "test_run_id": None,
                "duration": 0,
                "error": str(e),
            })
            if stop_on_failure:
                for remaining_id in test_case_ids[idx + 1:]:
                    skipped += 1
                    results.append({
                        "test_case_id": remaining_id,
                        "status": "skipped",
                        "test_run_id": None,
                        "duration": 0,
                        "error": "Skipped due to previous failure",
                    })
                break

    total = len(test_case_ids)
    suite_status = "passed" if failed == 0 and skipped == 0 else ("partial" if passed > 0 else "failed")

    logger.info(
        f"Suite run completed: {passed} passed, {failed} failed, {skipped} skipped / {total} total"
    )

    return {
        "suite_status": suite_status,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "success_rate": round((passed / total * 100) if total > 0 else 0, 1),
        "results": results,
    }


async def run_suite_smart(
    db: AsyncSession,
    suite_id: str,
    app_url: Optional[str] = None,
    browser: str = "chromium",
    headless: bool = True,
    stop_on_failure: bool = False,
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Two-phase optimised suite execution.

    Phase 1 — Parallel script generation:
        For every TC without an active script, take ONE DOM snapshot then run
        all generators concurrently (semaphore=3, each in its own DB session).

    Phase 2 — Single shared browser session:
        Open PlaywrightMCPClient once for the whole suite; execute each TC
        sequentially via run_with_tools() (no per-TC browser launch).
        Browser state is reset between TCs with a navigate() to app_url.
        Each TC is guarded by a 180 s timeout.
    """
    from sqlalchemy import select as _select
    from app.models.test_case import TestCase as _TC
    from app.models.test_suite import TestSuite as _TS
    from app.core.database import async_session_maker

    channel = f"suite_{suite_id}"

    # ── Load suite metadata ───────────────────────────────────────────────────
    tc_rows = (await db.execute(
        _select(_TC)
        .where(_TC.test_suite_id == suite_id, _TC.is_active == True)
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

    await _push_event(channel, "suite_started", {
        "suite_id": suite_id,
        "suite_title": suite_title,
        "test_case_ids": [tc.id for tc in tc_rows],
        "total": len(tc_rows),
        "app_url": app_url,
    })

    # ── Phase 1 — Parallel script generation ─────────────────────────────────
    shared_snapshots: Dict[str, str] = {}  # initialised here so Phase 2 always sees it
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

        # One multi-page snapshot set shared across all generators
        # Aggregate steps from all TCs needing scripts to maximise page coverage
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

    # ── Phase 2 — Single shared browser session ───────────────────────────────
    results: List[Dict[str, Any]] = []
    passed = failed = skipped = 0

    def _is_auth_tc(title: str, script_content: str) -> bool:
        """Heuristic: true when a TC performs a login/sign-in action."""
        kws = ("login", "sign in", "signin", "log in", "authenticate", "auth")
        if any(kw in title.lower() for kw in kws):
            return True
        sc = script_content.lower()
        return "password" in sc and ".fill(" in sc

    _saved_local_storage: Optional[str] = None  # JSON string of localStorage after auth TC

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
            # Use a self-invoking function to safely iterate and set entries
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

        # Navigate to app_url once to warm up the browser
        if app_url and "browser_navigate" in tools:
            try:
                await tools["browser_navigate"].ainvoke({"url": app_url})
                await asyncio.sleep(1.5)
            except Exception as warm_e:
                logger.warning(f"Browser warm-up navigate failed: {warm_e}")

        for idx, tc in enumerate(tc_rows):
            tc_id = tc.id

            await _push_event(channel, "tc_started", {
                "index": idx + 1,
                "total": len(tc_rows),
                "tc_id": tc_id,
                "tc_code": tc.tc_code,
                "title": tc.title,
            })

            # Re-query script (Phase 1 may have just created it)
            active_script = await repo.get_active_script(db, tc_id)
            if not active_script:
                logger.warning(f"Suite P2: no script for {tc.tc_code} — marking error")
                failed += 1
                tc_result = {
                    "tc_id": tc_id, "tc_code": tc.tc_code, "title": tc.title,
                    "status": "error", "run_id": None,
                    "steps_passed": 0, "steps_failed": 0, "duration": 0,
                    "error": "No script available (generation failed)",
                }
                results.append(tc_result)
                await _push_event(channel, "tc_completed", tc_result)
                if stop_on_failure:
                    for rem_tc in tc_rows[idx + 1:]:
                        skipped += 1
                        results.append({
                            "tc_id": rem_tc.id, "tc_code": rem_tc.tc_code,
                            "title": rem_tc.title, "status": "skipped",
                            "run_id": None, "steps_passed": 0, "steps_failed": 0,
                            "duration": 0, "error": "Skipped — previous TC failed",
                        })
                    break
                continue

            # Between TCs: do NOT navigate back to app_url.
            # The browser keeps whatever authenticated state TC (idx-1) left.
            # run_with_tools(suite_continuation=True) will skip the TC script's own
            # root navigate if the browser is already on an authenticated page,
            # preventing the "page.goto(app_url) → login redirect → wrong form filled"
            # failure pattern. A short pause lets any pending animations settle.
            if idx > 0:
                await asyncio.sleep(0.5)
                # Restore localStorage (JWT/tokens) for non-auth TCs that rely on a prior login
                if _saved_local_storage and not _is_auth_tc(tc.title, active_script.script_content if active_script else ""):
                    await _restore_local_storage(tools, _saved_local_storage)

            # Create TestRun record before execution
            test_run = await repo.create_test_run(
                db,
                script_version_id=active_script.id,
                base_url=app_url or settings.TEST_APPLICATION_URL,
                browser=browser,
                headless=headless,
            )
            await repo.commit(db)

            async def _on_step(label: str, status: str, error: str = None, _tc_id=tc_id):
                await _push_event(_tc_id, "agent_step", {
                    "step_type": "act",
                    "tool": "playwright",
                    "content": label,
                    "status": "success" if status == "passed" else "failed",
                    "error": error,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            try:
                exec_result = await asyncio.wait_for(
                    _react_agent.run_with_tools(
                        tools,
                        script_v1=active_script.script_content,
                        app_url=app_url or settings.TEST_APPLICATION_URL,
                        test_case_id=tc_id,
                        on_step=_on_step,
                        page_snapshots=shared_snapshots if shared_snapshots else {},
                        suite_continuation=(idx > 0),
                        model_id=model_id,
                    ),
                    timeout=180.0,
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
                await _save_execution_results(db, test_run.id, active_script, exec_result)
            except Exception as save_e:
                logger.error(f"Failed to save results for {tc.tc_code}: {save_e}")

            # After a successful auth TC, capture localStorage so subsequent TCs
            # that rely on stored tokens (JWT in localStorage) can restore it.
            if exec_result.get("execution_status") in ("passed", "completed"):
                if _is_auth_tc(tc.title, active_script.script_content):
                    captured = await _save_local_storage(tools)
                    if captured:
                        _saved_local_storage = captured

            raw_exec_status = exec_result.get("execution_status", "error")
            steps_failed_count = exec_result.get("steps_failed", 0)
            # Translate to the same status the DB stores (same logic as _save_exec_result_to_db)
            if raw_exec_status in ("passed", "completed") and steps_failed_count == 0:
                status = "passed"
            elif raw_exec_status == "error":
                status = "error"
            else:
                status = "failed"

            tc_result = {
                "tc_id": tc_id, "tc_code": tc.tc_code, "title": tc.title,
                "status": status,
                "run_id": test_run.id,
                "steps_passed": exec_result.get("steps_passed", 0),
                "steps_failed": exec_result.get("steps_failed", 0),
                "duration": round(exec_result.get("duration", 0) or 0, 1),
                "error": exec_result.get("error"),
            }
            results.append(tc_result)

            if status == "passed":
                passed += 1
            else:
                failed += 1

            await _push_event(channel, "tc_completed", tc_result)

            if failed > 0 and stop_on_failure:
                for rem_tc in tc_rows[idx + 1:]:
                    skipped += 1
                    skipped_result = {
                        "tc_id": rem_tc.id, "tc_code": rem_tc.tc_code,
                        "title": rem_tc.title, "status": "skipped",
                        "run_id": None, "steps_passed": 0, "steps_failed": 0,
                        "duration": 0, "error": "Skipped — previous TC failed",
                    }
                    results.append(skipped_result)
                    await _push_event(channel, "tc_completed", skipped_result)
                break

    # ── Final summary ─────────────────────────────────────────────────────────
    total = len(tc_rows)
    suite_status = "passed" if failed == 0 and skipped == 0 else ("partial" if passed > 0 else "failed")
    success_rate = round((passed / total * 100) if total > 0 else 0, 1)
    total_duration = round(sum(r.get("duration", 0) or 0 for r in results), 1)

    logger.info(f"Suite smart done: {passed} passed, {failed} failed, {skipped} skipped / {total}")

    await _push_event(channel, "completed", {
        "suite_id": suite_id,
        "suite_status": suite_status,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "success_rate": success_rate,
        "duration": total_duration,
        "results": results,
    })

    return {
        "suite_status": suite_status,
        "total": total, "passed": passed, "failed": failed,
        "skipped": skipped, "success_rate": success_rate, "results": results,
    }


async def _push_event(test_case_id: str, event_type: str, data: Dict[str, Any]) -> None:
    """Push event to SSE manager."""
    try:
        from app.streaming.sse_manager import push_event
        from app.ai_agents_v2.playwright_e2e.agent import format_tool_result
        
        # Formate le contenu pour les agent_step
        if event_type == "agent_step" and "tool" in data:
            tool_name = data.get("tool", "")
            content = data.get("content", "")
            if data.get("step_type") == "observe":
                formatted_content = format_tool_result(tool_name, content)
                data["content"] = formatted_content
        
        await push_event(test_case_id, event_type, data)
    except ImportError as e:
        logger.warning(f"SSE manager not available, event not sent: {event_type} - {e}")