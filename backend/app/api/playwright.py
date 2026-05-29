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
from app.models.enums import TestExecutionStatus

router = APIRouter(prefix="/playwright", tags=["Playwright E2E"])


# ============================================================
# SCHEMAS
# ============================================================

class GenerateScriptRequest(BaseModel):
    test_case_id: str
    app_url: Optional[str] = None
    model_id: Optional[str] = None


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
    model_id: Optional[str] = None


class FullWorkflowRequest(BaseModel):
    test_case_id: str
    app_url: Optional[str] = None
    browser: str = "chromium"
    headless: bool = True
    model_id: Optional[str] = None


class SuiteSmartRunRequest(BaseModel):
    """Execute all TCs in a suite: auto-generate missing scripts + run."""
    app_url: Optional[str] = None
    browser: str = Field(default="chromium", description="chromium, firefox, webkit")
    headless: bool = Field(default=True)
    stop_on_failure: bool = Field(default=False)
    model_id: Optional[str] = None


class SendReportEmailRequest(BaseModel):
    recipients: List[str] = Field(..., description="List of email addresses")


class CreateJiraIssueRequest(BaseModel):
    defect_id: str
    project_key: str
    priority: str = "High"


class CreateDefectRequest(BaseModel):
    test_case_id: str


class NotifyDeveloperRequest(BaseModel):
    recipients: List[str] = Field(default_factory=list, description="Developer email addresses")
    method: str = Field(default="email", description="email | jira | both")
    include_passed: bool = Field(default=False, description="Include passed TCs in the report")
    include_steps: bool = Field(default=True)
    include_screenshots: bool = Field(default=True)
    jira_project_key: Optional[str] = Field(default=None, description="Required if method=jira/both")
    jira_priority: str = Field(default="High")


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


# ============================================================
# BACKGROUND TASKS
# ============================================================

async def _execute_script_background(
    test_case_id: str,
    script_version_id: Optional[str],
    app_url: Optional[str],
    browser: str,
    headless: bool,
    model_id: Optional[str] = None,
    triggered_by: Optional[str] = None,
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
            model_id=model_id,
            triggered_by=triggered_by,
        )


async def _full_workflow_background(
    test_case_id: str,
    app_url: Optional[str],
    browser: str,
    headless: bool,
    model_id: Optional[str] = None,
):
    async with async_session_maker() as db:
        await service.run_full_workflow(
            db,
            test_case_id=test_case_id,
            app_url=app_url,
            browser=browser,
            headless=headless,
            model_id=model_id,
        )


async def _suite_smart_run_background(
    suite_id: str,
    app_url: Optional[str],
    browser: str,
    headless: bool,
    stop_on_failure: bool,
    model_id: Optional[str] = None,
    triggered_by: Optional[str] = None,
):
    async with async_session_maker() as db:
        await service.run_suite_smart(
            db,
            suite_id=suite_id,
            app_url=app_url,
            browser=browser,
            headless=headless,
            stop_on_failure=stop_on_failure,
            model_id=model_id,
            triggered_by=triggered_by,
        )


# ============================================================
# SCRIPT GENERATION & EXECUTION
# ============================================================

@router.post("/generate-script", response_model=GenerateScriptResponse)
async def generate_script_endpoint(
    request: GenerateScriptRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate a v1 Playwright script with placeholders."""
    try:
        result = await service.generate_script_v1(
            db,
            test_case_id=request.test_case_id,
            app_url=request.app_url,
            save_to_db=True,
            model_id=request.model_id,
        )
        return GenerateScriptResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute-script", response_model=AsyncStartResponse)
async def execute_script_endpoint(
    request: ExecuteScriptRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Trigger execution of a single test case (async, results via SSE)."""
    background_tasks.add_task(
        _execute_script_background,
        request.test_case_id,
        request.script_version_id,
        request.app_url,
        request.browser,
        request.headless,
        request.model_id,
        current_user.id,
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
    """Generation + execution chained in background."""
    background_tasks.add_task(
        _full_workflow_background,
        request.test_case_id,
        request.app_url,
        request.browser,
        request.headless,
        request.model_id,
    )
    return AsyncStartResponse(
        status="started",
        test_case_id=request.test_case_id,
        message=f"Workflow started. Connect to /playwright/test-case/{request.test_case_id}/stream for live updates.",
    )


# ============================================================
# TC RESULT — DETAIL, REPORT, EMAIL, DEFECT
# ============================================================

@router.get("/tc-result/{tc_result_id}/report")
async def get_full_report_endpoint(
    tc_result_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Full report for a single TestCaseResult (steps, defect, LLM reasoning)."""
    try:
        from app.services.execution_report_service import build_full_report
        report = await build_full_report(db, tc_result_id)
        if "error" in report:
            raise HTTPException(status_code=404, detail=report["error"])
        return report
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tc-result/{tc_result_id}/send-email")
async def send_report_email_endpoint(
    tc_result_id: str,
    request: SendReportEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send the execution report by email for a failed TC result."""
    try:
        from app.services.execution_report_service import build_full_report, send_execution_report_email
        if not request.recipients:
            raise HTTPException(status_code=400, detail="No recipients provided")

        report = await build_full_report(db, tc_result_id)
        if "error" in report:
            raise HTTPException(status_code=404, detail=report["error"])

        await send_execution_report_email(report=report, recipients=request.recipients)
        return {"status": "sent", "recipients": request.recipients, "tc_result_id": tc_result_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tc-result/{tc_result_id}/create-defect")
async def create_defect_endpoint(
    tc_result_id: str,
    request: CreateDefectRequest,
    db: AsyncSession = Depends(get_db),
):
    """Manually create a defect from a failed TC result."""
    try:
        from app.services.execution_report_service import create_defect_from_execution
        defect = await create_defect_from_execution(
            db,
            tc_result_id=tc_result_id,
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
    """Create a Jira Bug ticket from a TestForge defect."""
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


@router.get("/tc-result/{tc_result_id}")
async def get_tc_result_details_endpoint(
    tc_result_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Full TC result details (steps JSON, screenshot, etc.)."""
    try:
        result = await service.get_tc_result_details(db, tc_result_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# SCRIPT VERSIONS
# ============================================================

@router.get("/test-case/{test_case_id}/scripts", response_model=ScriptListResponse)
async def get_test_case_scripts_endpoint(
    test_case_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all script versions for a test case."""
    try:
        result = await service.get_test_case_scripts(db, test_case_id)
        return ScriptListResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/script/{script_version_id}")
async def get_script_content_endpoint(
    script_version_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Read a specific script version content."""
    from app.repositories import playwright_repository as repo
    script = await repo.get_script_version(db, script_version_id)
    if not script:
        raise HTTPException(status_code=404, detail=f"Script {script_version_id} not found")
    return {
        "id":                str(script.id),
        "content":           script.script_content,
        "version_number":    script.version_number,
        "source":            script.source,
        "is_active":         script.is_active,
        "placeholder_count": script.placeholder_count,
        "validation_status": script.validation_status,
        "created_at":        script.created_at.isoformat() if script.created_at else None,
    }


@router.delete("/script/{script_version_id}", status_code=200)
async def delete_script_version_endpoint(
    script_version_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete a specific script version. Promotes next-most-recent as active."""
    from app.repositories import playwright_repository as repo
    result = await repo.delete_script_version(db, script_version_id)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail=f"Script version {script_version_id} not found")
    await db.commit()
    return result


@router.delete("/test-case/{test_case_id}/scripts", status_code=200)
async def delete_all_scripts_endpoint(
    test_case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete all script versions for a test case."""
    from app.repositories import playwright_repository as repo
    result = await repo.delete_all_scripts_for_test_case(db, test_case_id)
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="No scripts found for this test case")
    await db.commit()
    return result


@router.patch("/script/{script_version_id}")
async def update_script_endpoint(
    script_version_id: str,
    request: UpdateScriptRequest,
    db: AsyncSession = Depends(get_db),
):
    """Save a manual edit as a new script version."""
    import re as _re
    from app.repositories import playwright_repository as repo
    from app.models.playwright_script_version import ScriptSource, ScriptValidationStatus  # noqa: F401

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

    await repo.update_test_case_after_execution(
        db,
        test_case_id=existing.test_case_id,
        active_script_id=str(new_version.id),
        locator_mapping={},
    )
    await db.commit()

    return {
        "id":                str(new_version.id),
        "version_number":    new_version.version_number,
        "source":            new_version.source,
        "is_active":         new_version.is_active,
        "placeholder_count": new_version.placeholder_count,
        "validation_status": new_version.validation_status,
        "created_at":        new_version.created_at.isoformat() if new_version.created_at else None,
    }


# ============================================================
# PER-TC HISTORY (last result + runs list)
# ============================================================

@router.get("/test-case/{test_case_id}/last-result")
async def get_last_tc_result_endpoint(
    test_case_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Most recent TestCaseResult for a TC, across all executions."""
    from app.repositories import playwright_repository as repo
    latest = await repo.get_latest_tc_result_for_test_case(db, test_case_id)
    if not latest:
        return {"message": f"No results found for test_case {test_case_id}"}
    return await service.get_tc_result_details(db, latest.id)


@router.get("/test-case/{test_case_id}/results")
async def list_tc_results_for_test_case_endpoint(
    test_case_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """All results for a TC across all executions, newest first."""
    from app.repositories import playwright_repository as repo
    results = await repo.list_tc_results_for_test_case(db, test_case_id, limit=limit)
    return {
        "results": [
            {
                "id":              r.id,
                "execution_id":    r.execution_id,
                "status":          r.status.value,
                "duration":        r.duration,
                "steps_passed":    r.steps_passed,
                "steps_failed":    r.steps_failed,
                "execution_order": r.execution_order,
                "started_at":      r.started_at.isoformat() if r.started_at else None,
                "completed_at":    r.completed_at.isoformat() if r.completed_at else None,
                "created_at":      r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
        ],
        "total": len(results),
    }


# ============================================================
# SSE STREAM
# ============================================================

@router.get("/test-case/{test_case_id}/stream")
async def stream_test_execution(request: Request, test_case_id: str):
    """SSE stream for a single TC execution."""
    return StreamingResponse(
        event_generator(test_case_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "Connection":        "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/test-case/{test_case_id}/stream/status")
async def stream_status_endpoint(test_case_id: str):
    return {"test_case_id": test_case_id, "buffered_events": event_buffer.get(test_case_id, [])}


# ============================================================
# TEST EXECUTIONS — LIST, DETAIL, STATS
# ============================================================

@router.get("/test-executions")
async def list_test_executions_endpoint(
    limit: int = 50,
    offset: int = 0,
    suite_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List paginated TestExecutions with global stats. Filtered by user's projects."""
    from app.repositories import playwright_repository as repo
    from app.models.test_suite import TestSuite
    from app.models.test_plan import TestPlan
    from app.models.user import User as _User
    from sqlalchemy import select as _sel

    project_ids = await get_user_project_ids(db, current_user.id)
    status_enum = None
    if status:
        try:
            status_enum = TestExecutionStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    listing = await repo.list_test_executions(
        db,
        limit=limit,
        offset=offset,
        suite_id=suite_id,
        status=status_enum,
        project_ids=project_ids,
    )
    stats = await repo.get_execution_global_stats(db, project_ids=project_ids)

    # Hydrate with suite_title / project_name / triggered_by_email
    items: List[Dict[str, Any]] = []
    for ex in listing["items"]:
        suite_row = await db.get(TestSuite, ex.suite_id)
        project_name = None
        if suite_row and suite_row.test_plan_id:
            plan = await db.get(TestPlan, suite_row.test_plan_id)
            project_name = getattr(plan, "project_name", None)
        triggered_email = None
        if ex.triggered_by:
            user_row = await db.get(_User, ex.triggered_by)
            triggered_email = user_row.email if user_row else None

        items.append({
            "id":                  ex.id,
            "suite_id":            ex.suite_id,
            "suite_title":         suite_row.title if suite_row else None,
            "project_name":        project_name,
            "app_url":             ex.app_url,
            "browser":             ex.browser,
            "headless":            ex.headless,
            "status":              ex.status.value,
            "started_at":          ex.started_at.isoformat() if ex.started_at else None,
            "completed_at":        ex.completed_at.isoformat() if ex.completed_at else None,
            "duration":            ex.duration,
            "total_count":         ex.total_count,
            "passed_count":        ex.passed_count,
            "failed_count":        ex.failed_count,
            "skipped_count":       ex.skipped_count,
            "error_count":         ex.error_count,
            "triggered_by_email":  triggered_email,
            "is_closed":           ex.is_closed,
            "closed_at":           ex.closed_at.isoformat() if ex.closed_at else None,
        })

    return {"items": items, "total": listing["total"], "stats": stats}


@router.get("/test-executions/{execution_id}")
async def get_test_execution_detail_endpoint(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Full execution detail with every TestCaseResult (status, steps, screenshot)."""
    from app.repositories import playwright_repository as repo
    from app.models.test_suite import TestSuite
    from app.models.test_case import TestCase

    ex = await repo.get_test_execution(db, execution_id)
    if not ex:
        raise HTTPException(status_code=404, detail=f"TestExecution {execution_id} not found")

    suite_row = await db.get(TestSuite, ex.suite_id)
    tc_results = await repo.list_tc_results_for_execution(db, execution_id)

    tc_results_data: List[Dict[str, Any]] = []
    for r in tc_results:
        tc_row = await db.get(TestCase, r.test_case_id)
        tc_results_data.append({
            "id":              r.id,
            "test_case_id":    r.test_case_id,
            "tc_code":         tc_row.tc_code if tc_row else None,
            "title":           tc_row.title if tc_row else None,
            "execution_order": r.execution_order,
            "status":          r.status.value,
            "duration":        r.duration,
            "steps_passed":    r.steps_passed,
            "steps_failed":    r.steps_failed,
            "steps":           r.steps or [],
            "justification":   r.justification,
            "error_message":   r.error_message,
            "screenshot_b64":  r.screenshot_b64,
            "script_version_id": r.script_version_id,
            "started_at":      r.started_at.isoformat() if r.started_at else None,
            "completed_at":    r.completed_at.isoformat() if r.completed_at else None,
        })

    return {
        "id":              ex.id,
        "suite_id":        ex.suite_id,
        "suite_title":     suite_row.title if suite_row else None,
        "app_url":         ex.app_url,
        "browser":         ex.browser,
        "headless":        ex.headless,
        "stop_on_failure": ex.stop_on_failure,
        "model_id":        ex.model_id,
        "status":          ex.status.value,
        "started_at":      ex.started_at.isoformat() if ex.started_at else None,
        "completed_at":    ex.completed_at.isoformat() if ex.completed_at else None,
        "duration":        ex.duration,
        "total_count":     ex.total_count,
        "passed_count":    ex.passed_count,
        "failed_count":    ex.failed_count,
        "skipped_count":   ex.skipped_count,
        "error_count":     ex.error_count,
        "is_closed":       ex.is_closed,
        "closed_at":       ex.closed_at.isoformat() if ex.closed_at else None,
        "test_case_results": tc_results_data,
    }


# ============================================================
# EXECUTION — NOTIFY DEVELOPER (suite-level report)
# ============================================================

@router.post("/test-executions/{execution_id}/notify-developer")
async def notify_developer_endpoint(
    execution_id: str,
    request: NotifyDeveloperRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a comprehensive report (email and/or Jira) for an entire execution."""
    from app.repositories import playwright_repository as repo
    from app.services.execution_report_service import (
        build_full_report, send_execution_report_email,
        create_defect_from_execution, create_jira_issue_from_defect,
    )

    method = (request.method or "email").lower()
    if method not in ("email", "jira", "both"):
        raise HTTPException(status_code=400, detail="method must be email | jira | both")

    if method in ("email", "both") and not request.recipients:
        raise HTTPException(status_code=400, detail="recipients required for email")

    if method in ("jira", "both") and not request.jira_project_key:
        raise HTTPException(status_code=400, detail="jira_project_key required for Jira")

    ex = await repo.get_test_execution(db, execution_id)
    if not ex:
        raise HTTPException(status_code=404, detail=f"TestExecution {execution_id} not found")

    tc_results = await repo.list_tc_results_for_execution(db, execution_id)
    if not tc_results:
        raise HTTPException(status_code=404, detail="No TC results to send")

    selected = [
        r for r in tc_results
        if request.include_passed or r.status.value in ("failed", "error")
    ]
    if not selected:
        raise HTTPException(status_code=400, detail="No matching test cases to notify")

    emails_sent = 0
    jira_keys: List[str] = []
    errors: List[str] = []

    for r in selected:
        is_failed = r.status.value in ("failed", "error")

        if method in ("email", "both"):
            try:
                report = await build_full_report(db, r.id)
                if "error" not in report:
                    if not request.include_steps:
                        report["steps"] = []
                    if not request.include_screenshots:
                        if report.get("tc_result"):
                            report["tc_result"]["screenshot_b64"] = None
                    await send_execution_report_email(report=report, recipients=request.recipients)
                    emails_sent += 1
            except Exception as e:
                errors.append(f"Email failed for {r.id}: {e}")

        if method in ("jira", "both") and is_failed:
            try:
                defect = await create_defect_from_execution(
                    db, tc_result_id=r.id, test_case_id=r.test_case_id
                )
                if defect and defect.get("id"):
                    await db.commit()
                    jira = await create_jira_issue_from_defect(
                        db,
                        defect_id=defect["id"],
                        user_id=current_user.id,
                        project_key=request.jira_project_key,
                        priority=request.jira_priority,
                    )
                    if jira and jira.get("key"):
                        jira_keys.append(jira["key"])
            except Exception as e:
                errors.append(f"Jira failed for {r.id}: {e}")

    return {
        "status": "notified",
        "execution_id": execution_id,
        "tc_count": len(selected),
        "emails_sent": emails_sent,
        "jira_issues": jira_keys,
        "errors": errors,
        "method": method,
    }


# ============================================================
# EXECUTION — CLOSE / REOPEN
# ============================================================

@router.post("/test-executions/{execution_id}/close")
async def close_execution_endpoint(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clôture une TestExecution (is_closed=true)."""
    from app.repositories import playwright_repository as repo
    ex = await repo.get_test_execution(db, execution_id)
    if not ex:
        raise HTTPException(status_code=404, detail=f"TestExecution {execution_id} not found")
    updated = await repo.close_test_execution(db, execution_id, closed_by=current_user.id)
    await db.commit()
    return {"is_closed": True, "closed_at": updated.closed_at, "closed_by": updated.closed_by}


@router.post("/test-executions/{execution_id}/reopen")
async def reopen_execution_endpoint(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Réouvre une TestExecution clôturée."""
    from app.repositories import playwright_repository as repo
    ex = await repo.get_test_execution(db, execution_id)
    if not ex:
        raise HTTPException(status_code=404, detail=f"TestExecution {execution_id} not found")
    await repo.reopen_test_execution(db, execution_id)
    await db.commit()
    return {"is_closed": False}


# ============================================================
# SUITE SMART EXECUTION
# ============================================================

@router.post("/suite/{suite_id}/execute-smart")
async def execute_suite_smart_endpoint(
    suite_id: str,
    request: SuiteSmartRunRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Launch the full suite execution in background. Stream via /suite/{id}/stream."""
    background_tasks.add_task(
        _suite_smart_run_background,
        suite_id,
        request.app_url,
        request.browser,
        request.headless,
        request.stop_on_failure,
        request.model_id,
        current_user.id,
    )
    return {
        "status": "started",
        "suite_id": suite_id,
        "stream_url": f"/playwright/suite/{suite_id}/stream",
        "message": f"Suite execution started. Connect to /playwright/suite/{suite_id}/stream for live updates.",
    }


@router.get("/suite/{suite_id}/stream")
async def stream_suite_execution(request: Request, suite_id: str):
    """SSE stream for suite-level execution."""
    return StreamingResponse(
        event_generator(f"suite_{suite_id}", request),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "Connection":        "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/suite/{suite_id}/scripts-status")
async def get_suite_scripts_status(
    suite_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Script status (has_script, placeholder_count) for every active TC in a suite."""
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
        if script is None:
            fallback = (await db.execute(
                _select(_PSV)
                .where(_PSV.test_case_id == tc.id, _PSV.is_active == True)
                .limit(1)
            )).scalar_one_or_none()
            if fallback:
                script = fallback
                tc.active_playwright_script_id = str(fallback.id)
                await db.flush()

        result.append({
            "tc_id":             tc.id,
            "tc_code":           tc.tc_code,
            "title":             tc.title,
            "has_script":        script is not None,
            "script_id":         str(script.id) if script else None,
            "version_number":    script.version_number if script else None,
            "placeholder_count": script.placeholder_count if script else None,
            "source":            script.source.value if script else None,
        })

    return {"suite_id": suite_id, "test_cases": result, "total": len(result)}


# ============================================================
# AVAILABLE MODELS
# ============================================================

@router.get("/models")
async def get_models_endpoint():
    """List LLM models available for script generation and execution."""
    from app.llm.llm_control import get_available_models
    return {"models": get_available_models()}


# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/health")
async def health_check_endpoint():
    """Playwright E2E service health."""
    from app.ai_agents_v2.playwright_e2e.config import MCP_PLAYWRIGHT_SERVER_URL
    return {
        "status": "healthy",
        "mcp_server_url": MCP_PLAYWRIGHT_SERVER_URL,
        "agents": {
            "script_generator": "available",
            "react_agent": "available",
        },
    }
