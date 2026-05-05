import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings

from app.repositories import playwright_repository as repo
from app.ai_agents_v2.playwright_e2e.script_generator import get_script_generator
from app.ai_agents_v2.playwright_e2e.agent import PlaywrightReActAgent
from app.models.enums import (
    ScriptSource, ScriptValidationStatus,
    TestRunStatus, TestResultStatus, StepType, StepStatus
)

logger = logging.getLogger(__name__)

# Initialisation des agents (globale)
_script_generator = get_script_generator()
_react_agent = PlaywrightReActAgent()


# ============================================================
# SCRIPT VERSIONS
# ============================================================

async def generate_script_v1(
    db: AsyncSession,
    test_case_id: str,
    save_to_db: bool = True
) -> Dict[str, Any]:
    """
    Génère un Script v1 avec placeholders à partir du TestCase en DB.
    """
    logger.info(f"Generating Script v1 for test_case {test_case_id}")
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

    gen_result = await _script_generator.generate(test_cases)

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

    try:
        exec_result = await _react_agent.run(
            script_v1=script_version.script_content,
            **({"app_url": app_url} if app_url else {}),
            test_case_id=test_case_id,
            headless=headless,
            browser=browser
        )

        if save_to_db and test_run:
            await _save_execution_results(
                db,
                test_run_id=test_run.id,
                script_version=script_version,
                exec_result=exec_result
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
    
    if exec_result.get("script_v2"):
        script_v2 = await repo.save_script(
            db,
            test_case_id=script_version.test_case_id,
            script_content=exec_result["script_v2"],
            source=ScriptSource.V2_CORRECTED,
            placeholder_count=exec_result.get("remaining_placeholders", 0),
            is_active=True
        )
        await repo.commit(db)
        
        await repo.update_test_run(
            db,
            test_run_id=test_run_id,
            status=final_status
        )
    
    raw_messages = exec_result.get("raw_messages", [])
    if raw_messages:
        steps = _extract_steps(raw_messages)
        if steps:
            await repo.add_steps_batch(db, test_run_id, steps)
    
    execution_status = exec_result.get("execution_status", "")
    test_result_status = (
        TestResultStatus.PASSED
        if execution_status in ("passed", "completed")
        else TestResultStatus.FAILED if execution_status == "failed"
        else TestResultStatus.ERROR
    )
    
    remaining = exec_result.get("remaining_placeholders", 0)
    total_ph = script_version.placeholder_count or 0
    resolved_ph = total_ph - remaining
    justification = (
        f"Placeholders: {resolved_ph}/{total_ph} resolved. "
        f"Steps: {exec_result.get('steps_passed', 0)} passed, {exec_result.get('steps_failed', 0)} failed."
    )
    await repo.save_test_result(
        db,
        test_run_id=test_run_id,
        status=test_result_status,
        justification=justification,
        step_count=exec_result.get("steps_passed", 0) + exec_result.get("steps_failed", 0)
    )
    
    await repo.commit(db)


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