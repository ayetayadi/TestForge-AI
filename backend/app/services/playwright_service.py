import asyncio
import logging
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


async def _take_landing_snapshot(app_url: str) -> Optional[str]:
    """
    Open a headless Chromium session, navigate to app_url, take one DOM snapshot,
    compress it to interactive elements only, and return it.
    Returns None if anything fails — generation falls back to blind mode.
    """
    try:
        logger.info(f"Taking landing page snapshot for: {app_url}")
        async with PlaywrightMCPClient(headless=True, browser="chromium") as mcp:
            tools = {t.name: t for t in mcp.tools}
            if "browser_navigate" not in tools or "browser_snapshot" not in tools:
                logger.warning("Landing snapshot: required MCP tools unavailable")
                return None
            await tools["browser_navigate"].ainvoke({"url": app_url})
            await asyncio.sleep(2.0)
            raw = str(await tools["browser_snapshot"].ainvoke({}))
            snapshot = _agent_instance._extract_snapshot_text(raw)
            compressed = _compress_dom(snapshot)
            logger.info(f"Landing snapshot captured ({len(compressed)} chars)")
            return compressed
    except Exception as e:
        logger.warning(f"Landing snapshot failed — falling back to blind generation: {e}")
        return None


# ============================================================
# SCRIPT VERSIONS
# ============================================================

async def generate_script_v1(
    db: AsyncSession,
    test_case_id: str,
    app_url: Optional[str] = None,
    save_to_db: bool = True,
    dom_snapshot: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Génère un Script v1 à partir du TestCase en DB.
    Si app_url est fourni et dom_snapshot est None, ouvre le navigateur pour capturer le DOM.
    Passer dom_snapshot pré-capturé pour éviter d'ouvrir une connexion navigateur supplémentaire.
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
        "priority": test_case.priority,
        "preconditions": test_case.preconditions,
        "postconditions": test_case.postconditions,
        "steps": test_case.steps,
        "gherkin_source": test_case.gherkin_source,
        "test_data": test_case.test_data,
        "expected_results": test_case.expected_results,
        "locators": test_case.locators,
    }]

    if dom_snapshot is None and app_url:
        dom_snapshot = await _take_landing_snapshot(app_url)

    gen_result = await _script_generator.generate(test_cases, dom_snapshot=dom_snapshot, app_url=app_url)

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
            validation_status=ScriptValidationStatus.NOT_VALIDATED
        )
        await repo.commit(db)
        
        gen_result["script_version_id"] = script_version.id
        gen_result["version_number"] = script_version.version_number

    await _push_event(test_case_id, "generation_completed", {
        "placeholder_count": gen_result["placeholder_count"],
        "script_version_id": gen_result.get("script_version_id"),
    })
    return gen_result


async def execute_script(
    db: AsyncSession,
    test_case_id: str,
    script_version_id: Optional[str] = None,
    app_url: Optional[str] = None,
    browser: str = "chromium",   # Valeur par défaut (normalement écrasée par frontend)
    headless: bool = True,       # Valeur par défaut (normalement écrasée par frontend)
    save_to_db: bool = True
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
    headless: bool = True
) -> Dict[str, Any]:
    """Workflow complet: Génération + Exécution."""
    logger.info(f"Starting full workflow for test_case {test_case_id}")

    gen_result = await generate_script_v1(
        db,
        test_case_id=test_case_id,
        save_to_db=True
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
        save_to_db=True
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

            status = exec_result.get("execution_status", "error")
            results.append({
                "test_case_id": tc_id,
                "status": status,
                "test_run_id": exec_result.get("test_run_id"),
                "duration": exec_result.get("duration", 0),
                "error": exec_result.get("error"),
            })

            if status in ("passed", "completed"):
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

        # One DOM snapshot shared by all generators (avoids N browser launches)
        shared_snapshot: Optional[str] = None
        if app_url:
            shared_snapshot = await _take_landing_snapshot(app_url)

        _gen_sem = asyncio.Semaphore(3)

        async def _gen_one(tc) -> None:
            async with _gen_sem:
                async with async_session_maker() as session:
                    try:
                        result = await generate_script_v1(
                            session, tc.id,
                            app_url=app_url,
                            save_to_db=True,
                            dom_snapshot=shared_snapshot,
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

            # Reset browser to app_url between TCs (skip for first TC — already done)
            if idx > 0 and app_url and "browser_navigate" in tools:
                try:
                    await tools["browser_navigate"].ainvoke({"url": app_url})
                    await asyncio.sleep(1.0)
                except Exception as nav_e:
                    logger.warning(f"Browser reset failed for {tc.tc_code}: {nav_e}")

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

            status = exec_result.get("execution_status", "error")
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

            if status in ("passed", "completed"):
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