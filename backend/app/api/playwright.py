from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from app.core.database import get_db, async_session_maker
from app.services import playwright_service as service
from app.streaming.sse_manager import event_generator, event_buffer
from app.api.deps import get_current_user, get_user_project_ids
from app.models.user import User

router = APIRouter(prefix="/playwright", tags=["Playwright E2E"])


# ============================================================
# SCHEMAS
# ============================================================

class GenerateScriptRequest(BaseModel):
    test_case_id: str
    app_url: Optional[str] = None


class GenerateScriptResponse(BaseModel):
    status: str
    script_v1: str
    placeholder_count: int
    model_used: str
    script_version_id: Optional[str] = None
    version_number: Optional[int] = None
    warning: Optional[str] = None
    error: Optional[str] = None


class ExecuteScriptRequest(BaseModel):
    test_case_id: str
    script_version_id: Optional[str] = None
    app_url: Optional[str] = None
    browser: str = Field(default="chromium", description="chromium, firefox, webkit")
    headless: bool = Field(default=True, description="Run in headless mode")


class FullWorkflowRequest(BaseModel):
    """Requête pour le workflow complet (génération + exécution)."""
    test_case_id: str
    app_url: Optional[str] = None
    browser: str = "chromium"
    headless: bool = True


class SuiteRunRequest(BaseModel):
    """Requête pour exécuter plusieurs test cases en ordre séquentiel."""
    test_case_ids: List[str] = Field(..., description="IDs dans l'ordre d'exécution")
    app_url: Optional[str] = None
    browser: str = "chromium"
    headless: bool = True
    stop_on_failure: bool = Field(default=False, description="Stop suite if a TC fails")


class SuiteSmartRunRequest(BaseModel):
    """Execute all TCs in a suite: auto-generate missing scripts + resolve + run."""
    app_url: Optional[str] = None
    browser: str = Field(default="chromium", description="chromium, firefox, webkit")
    headless: bool = Field(default=True)
    stop_on_failure: bool = Field(default=False)


class SendReportEmailRequest(BaseModel):
    recipients: List[str] = Field(..., description="List of email addresses")


class CreateJiraIssueRequest(BaseModel):
    defect_id: str
    project_key: str
    priority: str = "High"


class CreateDefectRequest(BaseModel):
    test_case_id: str


class UpdateScriptRequest(BaseModel):
    script_content: str = Field(..., min_length=1, description="Edited TypeScript content")


class AsyncStartResponse(BaseModel):
    status: str
    test_case_id: str
    message: str


class ScriptListResponse(BaseModel):
    test_case_id: str
    active_script_id: Optional[str]
    scripts: List[Dict[str, Any]]


class TestRunDetailsResponse(BaseModel):
    test_run: Dict[str, Any]
    result: Optional[Dict[str, Any]]
    steps: List[Dict[str, Any]]


# ============================================================
# BACKGROUND TASKS
# ============================================================

async def _execute_script_background(
    test_case_id: str,
    script_version_id: Optional[str],
    app_url: Optional[str],
    browser: str,
    headless: bool,
):
    async with async_session_maker() as db:
        await service.execute_script(
            db,
            test_case_id=test_case_id,
            script_version_id=script_version_id,
            app_url=app_url,
            browser=browser,
            headless=headless,
            save_to_db=True,
        )


async def _full_workflow_background(
    test_case_id: str,
    app_url: Optional[str],
    browser: str,
    headless: bool,
):
    async with async_session_maker() as db:
        await service.run_full_workflow(
            db,
            test_case_id=test_case_id,
            app_url=app_url,
            browser=browser,
            headless=headless,
        )


async def _suite_smart_run_background(
    suite_id: str,
    app_url: Optional[str],
    browser: str,
    headless: bool,
    stop_on_failure: bool,
):
    async with async_session_maker() as db:
        await service.run_suite_smart(
            db,
            suite_id=suite_id,
            app_url=app_url,
            browser=browser,
            headless=headless,
            stop_on_failure=stop_on_failure,
        )


async def _suite_run_background(
    test_case_ids: List[str],
    app_url: Optional[str],
    browser: str,
    headless: bool,
    stop_on_failure: bool,
):
    async with async_session_maker() as db:
        await service.run_suite(
            db,
            test_case_ids=test_case_ids,
            app_url=app_url,
            browser=browser,
            headless=headless,
            stop_on_failure=stop_on_failure,
        )


# ============================================================
# ENDPOINTS
# ============================================================

@router.post("/generate-script", response_model=GenerateScriptResponse)
async def generate_script_endpoint(
    request: GenerateScriptRequest,
    db: AsyncSession = Depends(get_db)
):
    """Génère un Script v1 avec placeholders à partir des cas de test."""
    try:
        result = await service.generate_script_v1(
            db,
            test_case_id=request.test_case_id,
            app_url=request.app_url,
            save_to_db=True,
        )
        
        return GenerateScriptResponse(**result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute-script", response_model=AsyncStartResponse)
async def execute_script_endpoint(
    request: ExecuteScriptRequest,
    background_tasks: BackgroundTasks,
):
    """Lance l'exécution du script en arrière-plan (résultats via SSE)."""
    background_tasks.add_task(
        _execute_script_background,
        request.test_case_id,
        request.script_version_id,
        request.app_url,
        request.browser,
        request.headless,
    )
    return AsyncStartResponse(
        status="started",
        test_case_id=request.test_case_id,
        message=f"Execution started. Connect to /playwright/test-case/{request.test_case_id}/stream for live updates.",
    )


@router.post("/full-workflow", response_model=AsyncStartResponse)
async def full_workflow_endpoint(
    request: FullWorkflowRequest,
    background_tasks: BackgroundTasks,
):
    """Workflow complet: Génération + Exécution en arrière-plan."""
    background_tasks.add_task(
        _full_workflow_background,
        request.test_case_id,
        request.app_url,
        request.browser,
        request.headless,
    )
    return AsyncStartResponse(
        status="started",
        test_case_id=request.test_case_id,
        message=f"Workflow started. Connect to /playwright/test-case/{request.test_case_id}/stream for live updates.",
    )


@router.post("/run-suite", response_model=AsyncStartResponse)
async def run_suite_endpoint(
    request: SuiteRunRequest,
    background_tasks: BackgroundTasks,
):
    """Exécute plusieurs test cases séquentiellement dans l'ordre fourni."""
    if not request.test_case_ids:
        raise HTTPException(status_code=400, detail="test_case_ids list is empty")

    background_tasks.add_task(
        _suite_run_background,
        request.test_case_ids,
        request.app_url,
        request.browser,
        request.headless,
        request.stop_on_failure,
    )
    return AsyncStartResponse(
        status="started",
        test_case_id=request.test_case_ids[0],
        message=f"Suite run started: {len(request.test_case_ids)} test cases. Monitor each TC's SSE stream.",
    )


@router.get("/test-run/{test_run_id}/report")
async def get_full_report_endpoint(
    test_run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retourne le rapport complet d'un test run (steps, résultat, defect, raisonnement LLM)."""
    try:
        from app.services.execution_report_service import build_full_report
        report = await build_full_report(db, test_run_id)
        if "error" in report:
            raise HTTPException(status_code=404, detail=report["error"])
        return report
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-run/{test_run_id}/send-email")
async def send_report_email_endpoint(
    test_run_id: str,
    request: SendReportEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Envoie le rapport d'exécution par email aux destinataires spécifiés."""
    try:
        from app.services.execution_report_service import build_full_report, send_execution_report_email
        if not request.recipients:
            raise HTTPException(status_code=400, detail="No recipients provided")

        report = await build_full_report(db, test_run_id)
        if "error" in report:
            raise HTTPException(status_code=404, detail=report["error"])

        await send_execution_report_email(report=report, recipients=request.recipients)
        return {"status": "sent", "recipients": request.recipients, "test_run_id": test_run_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-run/{test_run_id}/create-defect")
async def create_defect_endpoint(
    test_run_id: str,
    request: CreateDefectRequest,
    db: AsyncSession = Depends(get_db),
):
    """Crée manuellement un defect à partir d'un test run échoué."""
    try:
        from app.services.execution_report_service import create_defect_from_execution
        defect = await create_defect_from_execution(
            db,
            test_run_id=test_run_id,
            test_case_id=request.test_case_id,
        )
        if not defect:
            raise HTTPException(
                status_code=422,
                detail="Cannot create defect: test case must be linked to a user story.",
            )
        await db.commit()
        return defect
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/defect/{defect_id}/create-jira")
async def create_jira_from_defect_endpoint(
    defect_id: str,
    request: CreateJiraIssueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Crée un ticket Jira Bug à partir d'un defect TestForge."""
    try:
        from app.services.execution_report_service import create_jira_issue_from_defect
        result = await create_jira_issue_from_defect(
            db,
            defect_id=defect_id,
            user_id=current_user.id,
            project_key=request.project_key,
            priority=request.priority,
        )
        return result
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/test-case/{test_case_id}/scripts", response_model=ScriptListResponse)
async def get_test_case_scripts_endpoint(
    test_case_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Récupère tous les scripts d'un test case."""
    try:
        result = await service.get_test_case_scripts(db, test_case_id)
        return ScriptListResponse(**result)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/test-run/{test_run_id}", response_model=TestRunDetailsResponse)
async def get_test_run_details_endpoint(
    test_run_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Récupère les détails complets d'un test run."""
    try:
        result = await service.get_test_run_details(db, test_run_id)
        
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        
        return TestRunDetailsResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/script/{script_version_id}")
async def get_script_content_endpoint(
    script_version_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Récupère le contenu d'un script spécifique."""
    from app.repositories import playwright_repository as repo
    script = await repo.get_script_version(db, script_version_id)
    if not script:
        raise HTTPException(status_code=404, detail=f"Script {script_version_id} not found")
    return {
        "id": str(script.id),
        "content": script.script_content,
        "version_number": script.version_number,
        "source": script.source,
        "is_active": script.is_active,
        "placeholder_count": script.placeholder_count,
        "validation_status": script.validation_status,
        "created_at": script.created_at.isoformat() if script.created_at else None,
    }


@router.patch("/script/{script_version_id}")
async def update_script_endpoint(
    script_version_id: str,
    request: UpdateScriptRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Save a manual edit as a new script version.
    Creates a new PlaywrightScriptVersion with source=MANUAL_EDIT, marks it active,
    and updates TestCase.active_playwright_script_id.
    Preserves the original version in history.
    """
    import re as _re
    from app.repositories import playwright_repository as repo
    from app.models.playwright_script_version import ScriptSource, ScriptValidationStatus

    existing = await repo.get_script_version(db, script_version_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Script {script_version_id} not found")

    placeholder_count = len(_re.findall(r'\[TESTFORGEAI:', request.script_content))

    new_version = await repo.save_script(
        db,
        test_case_id=existing.test_case_id,
        script_content=request.script_content,
        source=ScriptSource.MANUAL_EDIT,
        placeholder_count=placeholder_count,
        is_active=True,
    )

    # Keep TestCase.active_playwright_script_id in sync
    await repo.update_test_case_after_execution(
        db,
        test_case_id=existing.test_case_id,
        active_script_id=str(new_version.id),
        locator_mapping={},
    )

    await db.commit()

    return {
        "id": str(new_version.id),
        "version_number": new_version.version_number,
        "source": new_version.source,
        "is_active": new_version.is_active,
        "placeholder_count": new_version.placeholder_count,
        "validation_status": new_version.validation_status,
        "created_at": new_version.created_at.isoformat() if new_version.created_at else None,
    }


@router.get("/test-case/{test_case_id}/last-run")
async def get_last_test_run_endpoint(
    test_case_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Récupère le dernier test run pour un test case (toutes versions de script)."""
    try:
        from app.repositories import playwright_repository as repo

        latest_run = await repo.get_latest_run_for_test_case(db, test_case_id)

        if not latest_run:
            return {"message": f"No test runs found for test_case {test_case_id}"}

        return await service.get_test_run_details(db, latest_run.id)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/test-case/{test_case_id}/runs")
async def get_test_case_runs_endpoint(
    test_case_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Liste tous les runs d'un test case (toutes versions de script), du plus récent au plus ancien."""
    try:
        from app.repositories import playwright_repository as repo

        runs = await repo.get_runs_for_test_case(db, test_case_id, limit=limit)

        result_list = []
        for run in runs:
            result_obj = await repo.get_test_result(db, run.id)
            script_version = (
                await repo.get_script_version(db, run.script_version_id)
                if run.script_version_id else None
            )
            result_list.append({
                "id": run.id,
                "status": run.status.value,
                "browser": run.browser,
                "duration": run.duration,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "result_status": result_obj.status.value if result_obj else None,
                "result_step_count": result_obj.step_count if result_obj else 0,
                "script_version_number": script_version.version_number if script_version else None,
            })

        return {"runs": result_list, "total": len(result_list)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# SSE STREAM
# ============================================================

@router.get("/test-case/{test_case_id}/stream")
async def stream_test_execution(request: Request, test_case_id: str):
    """Stream SSE pour suivre l'exécution d'un test case en temps réel."""
    return StreamingResponse(
        event_generator(test_case_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/test-case/{test_case_id}/stream/status")
async def stream_status_endpoint(test_case_id: str):
    """Retourne les événements bufferisés pour un test case."""
    return {"test_case_id": test_case_id, "buffered_events": event_buffer.get(test_case_id, [])}


# ============================================================
# TEST RUNS — LIST & STATS
# ============================================================

@router.get("/test-runs")
async def list_test_runs_endpoint(
    limit: int = 50,
    offset: int = 0,
    result_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Liste les test runs de l'utilisateur avec contexte complet.
    result_filter: passed | failed | error | skipped | all
    """
    try:
        from app.repositories.playwright_repository import get_all_test_runs_with_context
        project_ids = await get_user_project_ids(db, current_user.id)
        data = await get_all_test_runs_with_context(
            db,
            limit=limit,
            offset=offset,
            result_filter=result_filter if result_filter and result_filter != "all" else None,
            project_ids=project_ids,
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# SUITE SMART EXECUTION
# ============================================================

@router.post("/suite/{suite_id}/execute-smart")
async def execute_suite_smart_endpoint(
    suite_id: str,
    request: SuiteSmartRunRequest,
    background_tasks: BackgroundTasks,
):
    """
    Execute all test cases in a suite sequentially.
    Auto-generates Playwright scripts for TCs that don't have one yet.
    Stream progress via GET /playwright/suite/{suite_id}/stream.
    """
    background_tasks.add_task(
        _suite_smart_run_background,
        suite_id,
        request.app_url,
        request.browser,
        request.headless,
        request.stop_on_failure,
    )
    return {
        "status": "started",
        "suite_id": suite_id,
        "stream_url": f"/playwright/suite/{suite_id}/stream",
        "message": f"Suite execution started. Connect to /playwright/suite/{suite_id}/stream for live updates.",
    }


@router.get("/suite/{suite_id}/stream")
async def stream_suite_execution(request: Request, suite_id: str):
    """SSE stream for suite-level execution progress."""
    return StreamingResponse(
        event_generator(f"suite_{suite_id}", request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/suite/{suite_id}/last-run")
async def get_suite_last_run(
    suite_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the most recent run result for every active TC in a suite.
    Used to restore the execution panel after navigating away and back.
    """
    from sqlalchemy import select as _select
    from app.models.test_case import TestCase as _TC
    from app.repositories import playwright_repository as repo

    tc_rows = (await db.execute(
        _select(_TC)
        .where(_TC.test_suite_id == suite_id, _TC.is_active == True)
        .order_by(_TC.execution_order.asc().nullslast(), _TC.tc_code.asc())
    )).scalars().all()

    results = []
    passed = failed = 0
    total_duration = 0.0
    has_runs = False

    for tc in tc_rows:
        latest_run = await repo.get_latest_run_for_test_case(db, tc.id)
        if latest_run:
            has_runs = True
            result_obj = await repo.get_test_result(db, latest_run.id)
            if (
                latest_run.status.value == "completed"
                and (result_obj is None or result_obj.status.value == "passed")
            ):
                tc_status = "passed"
                passed += 1
            else:
                tc_status = "failed"
                failed += 1
            total_duration += latest_run.duration or 0.0
        else:
            tc_status = "pending"

        results.append({
            "tc_id": tc.id,
            "tc_code": tc.tc_code,
            "title": tc.title,
            "status": tc_status,
            "run_id": latest_run.id if latest_run else None,
            "duration": latest_run.duration if latest_run else None,
            "started_at": latest_run.started_at.isoformat() if latest_run and latest_run.started_at else None,
        })

    return {
        "suite_id": suite_id,
        "has_runs": has_runs,
        "results": results,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": 0,
            "duration": round(total_duration, 1),
        } if has_runs else None,
    }


@router.get("/suite/{suite_id}/scripts-status")
async def get_suite_scripts_status(
    suite_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the Playwright script status for every active TC in a suite.
    Used by the frontend 'Review Scripts' step before launching execution.
    """
    from sqlalchemy import select as _select
    from app.models.test_case import TestCase as _TC
    from app.models.playwright_script_version import PlaywrightScriptVersion as _PSV

    tc_rows = (await db.execute(
        _select(_TC)
        .where(_TC.test_suite_id == suite_id, _TC.is_active == True)
        .order_by(_TC.execution_order.asc().nullslast(), _TC.tc_code.asc())
    )).scalars().all()

    result = []
    for tc in tc_rows:
        script = None
        if tc.active_playwright_script_id:
            script = await db.get(_PSV, tc.active_playwright_script_id)

        result.append({
            "tc_id": tc.id,
            "tc_code": tc.tc_code,
            "title": tc.title,
            "has_script": script is not None,
            "script_id": script.id if script else None,
            "version_number": script.version_number if script else None,
            "placeholder_count": script.placeholder_count if script else None,
            "source": script.source.value if script else None,
        })

    return {"suite_id": suite_id, "test_cases": result, "total": len(result)}


# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/health")
async def health_check_endpoint():
    """Vérifie l'état du service Playwright E2E."""
    from app.ai_agents_v2.playwright_e2e.config import MCP_PLAYWRIGHT_SERVER_URL
    
    return {
        "status": "healthy",
        "mcp_server_url": MCP_PLAYWRIGHT_SERVER_URL,
        "agents": {
            "script_generator": "available",
            "react_agent": "available"
        }
    }