from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from app.core.database import get_db, async_session_maker
from app.services import playwright_service as service
from app.streaming.sse_manager import event_generator, event_buffer

router = APIRouter(prefix="/playwright", tags=["Playwright E2E"])


# ============================================================
# SCHEMAS
# ============================================================

class GenerateScriptRequest(BaseModel):
    test_case_id: str


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
            save_to_db=True
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


@router.get("/test-case/{test_case_id}/last-run")
async def get_last_test_run_endpoint(
    test_case_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Récupère le dernier test run pour un test case."""
    try:
        from app.repositories import playwright_repository as repo
        
        active_script = await repo.get_active_script(db, test_case_id)
        
        if not active_script:
            return {"error": f"No active script for test_case {test_case_id}"}
        
        runs = await repo.get_test_runs_by_script(db, active_script.id, limit=1)
        
        if not runs:
            return {"message": f"No test runs found for test_case {test_case_id}"}
        
        return await service.get_test_run_details(db, runs[0].id)
        
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