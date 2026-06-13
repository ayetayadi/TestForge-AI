"""
Test Cases API - CRUD operations and workflow-based generation (ISTQB §5.4 pipeline).

Endpoints:
  - GET  /test-cases                 → List test cases with filters
  - GET  /test-cases/{id}            → Get test case by ID
  - GET  /test-cases/by-code/{code}  → Get test case by TC code
  - GET  /test-cases/suite/{id}      → Get test cases by test suite
  - GET  /test-cases/plan/{id}       → Get test cases by test plan
  - POST /test-cases                 → Create new test case
  - PUT  /test-cases/{id}            → Update test case
  - DELETE /test-cases/{id}          → Soft delete test case
  
  - POST /test-cases/generate/{test_plan_id}           → Sync generation
  - POST /test-cases/generate/{test_plan_id}/async     → Async generation
  - GET  /test-cases/generate/stream/{job_id}           → SSE stream
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_user_project_ids
from app.core.database import get_db
from app.models.test_plan import TestPlan
from app.models.user import User
from app.services import test_case_service as service
from app.workers.tc_worker import submit_tc_job
from app.streaming.sse_manager import connections, event_buffer
from app.schemas.test_case_schema import (
    TestCaseResponse,
    CreateTestCaseRequest,
    UpdateTestCaseRequest,
    GenerateTestCasesResponse,
    GeneratedTestCaseResponse,
    AsyncTcJobResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test-cases", tags=["Test Cases"])

# ============================================================
# CRUD ENDPOINTS
# ============================================================

@router.get("", response_model=List[TestCaseResponse])
@router.get("/", response_model=List[TestCaseResponse], include_in_schema=False)
async def get_all_test_cases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    test_suite_id: Optional[str] = Query(None, description="Filter by test suite ID"),
    test_plan_id: Optional[str] = Query(None, description="Filter by test plan ID"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    search: Optional[str] = Query(None, description="Search in title or code"),
    status: Optional[List[str]] = Query(None, description="Filter by status (active/archived)"),
    risk_level: Optional[List[str]] = Query(None, description="Filter by risk level"),
    order_by: str = Query("created_at", description="Sort field"),
    order_direction: str = Query("desc", description="Sort direction"),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
):
    """Récupère les test cases de l'utilisateur avec filtres."""
    try:
        project_ids = await get_user_project_ids(db, current_user.id)
        result = await service.get_all_test_cases(
            db,
            test_suite_id=test_suite_id,
            test_plan_id=test_plan_id,
            project_id=project_id,
            project_ids=project_ids,
            search=search,
            status=status,
            risk_level=risk_level,
            order_by=order_by,
            order_direction=order_direction,
            limit=limit,
            offset=offset,
        )
        return result
    except Exception as e:
        logger.error(f"[TC_API] Error listing test cases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{test_case_id}", response_model=TestCaseResponse)
async def get_test_case_by_id(
    test_case_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Récupère un test case par son ID."""
    try:
        test_case = await service.get_test_case_by_id(db, test_case_id)
        if not test_case:
            raise HTTPException(status_code=404, detail="Test case not found")
        return await service.format_for_frontend(test_case, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-code/{tc_code}", response_model=TestCaseResponse)
async def get_test_case_by_code(
    tc_code: str,
    db: AsyncSession = Depends(get_db)
):
    """Récupère un test case par son code (ex: TC-001)."""
    try:
        test_case = await service.get_test_case_by_code(db, tc_code)
        if not test_case:
            raise HTTPException(status_code=404, detail="Test case not found")
        return await service.format_for_frontend(test_case, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/coverage/{test_plan_id}", summary="AC coverage table for a test plan")
async def get_tc_coverage(
    test_plan_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Returns coverage rows per (user_story, scenario_type) for a test plan."""
    try:
        return await service.get_tc_coverage_for_plan(db, test_plan_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suite/{test_suite_id}", response_model=List[TestCaseResponse])
async def get_test_cases_by_test_suite(
    test_suite_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Récupère tous les test cases d'une suite."""
    try:
        test_cases = await service.get_test_cases_by_test_suite(db, test_suite_id)
        formatted = []
        for tc in test_cases:
            formatted.append(await service.format_for_frontend(tc, db))
        return formatted
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/plan/{test_plan_id}", response_model=List[TestCaseResponse])
async def get_test_cases_by_test_plan(
    test_plan_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Récupère tous les test cases d'un plan (via les suites)."""
    try:
        test_cases = await service.get_test_cases_by_test_plan(db, test_plan_id)
        formatted = []
        for tc in test_cases:
            formatted.append(await service.format_for_frontend(tc, db))
        return formatted
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_test_case(
    request: CreateTestCaseRequest,
    db: AsyncSession = Depends(get_db)
):
    """Crée un nouveau test case (test_suite_id optionnel)."""
    try:
        test_case = await service.create_test_case(db, request.model_dump())
        await db.commit()
        await db.refresh(test_case)
        return await service.format_for_frontend(test_case, db)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{test_case_id}", response_model=TestCaseResponse)
async def update_test_case(
    test_case_id: str,
    request: UpdateTestCaseRequest,
    db: AsyncSession = Depends(get_db)
):
    """Met à jour un test case existant."""
    try:
        test_case = await service.update_test_case(
            db, test_case_id, request.model_dump(exclude_none=True)
        )
        if not test_case:
            raise HTTPException(status_code=404, detail="Test case not found")
        await db.commit()
        await db.refresh(test_case)
        return await service.format_for_frontend(test_case, db)
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))



@router.delete("/{test_case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    test_case_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Supprime (soft delete) un test case."""
    try:
        success = await service.delete_test_case(db, test_case_id)
        if not success:
            raise HTTPException(status_code=404, detail="Test case not found")
        await db.commit()
        return None
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# GENERATION ENDPOINTS
# ============================================================

@router.post(
    "/generate/{test_plan_id}",
    response_model=GenerateTestCasesResponse,
    summary="Generate test cases for a test plan (sync)",
)
async def generate_test_cases_sync(
    test_plan_id: str,
    db: AsyncSession = Depends(get_db),
    test_suite_id: Optional[str] = Query(None, description="Optional suite to assign TCs to"),
    risk_level: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
    risk_score: Optional[float] = Query(None, ge=0.0, le=5.0),
    risk_description: Optional[str] = Query(None),
    scenario_type: Optional[str] = Query(None, pattern="^(positive|negative|boundary)$", description="positive | negative | boundary"),
) -> GenerateTestCasesResponse:
    """Génération synchrone pour un plan de test. Suite optionnelle."""
    try:
        result = await service.generate_test_cases_for_plan(
            db=db,
            test_plan_id=test_plan_id,
            test_suite_id=test_suite_id,
            risk_level=risk_level,
            risk_score=risk_score,
            risk_description=risk_description,
            scenario_type=scenario_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("[TC_GEN_API] Unexpected error for plan=%s", test_plan_id)
        raise HTTPException(status_code=500, detail=f"Internal error: {exc}")

    if result.get("workflow_status") == "error":
        await db.rollback()
        return GenerateTestCasesResponse(
            count=0,
            test_plan_id=test_plan_id,
            test_suite_id=test_suite_id,
            workflow_status="error",
            error=result.get("error", "Unknown pipeline error"),
        )

    await db.commit()

    return GenerateTestCasesResponse(
        count=result["count"],
        test_plan_id=test_plan_id,
        test_suite_id=test_suite_id,
        workflow_status="success",
        feature_gherkin=result.get("feature_gherkin", ""),
        coverage_hints=result.get("coverage_hints", []),
        test_cases=[
            GeneratedTestCaseResponse(**tc)
            for tc in result.get("test_cases", [])
        ],
    )


@router.post(
    "/generate/{test_plan_id}/async",
    response_model=AsyncTcJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue async test case generation",
)
async def generate_test_cases_async(
    test_plan_id: str,
    db: AsyncSession = Depends(get_db),
    test_suite_id: Optional[str] = Query(None, description="Optional suite to assign TCs to"),
    scenario_type: Optional[str] = Query(None, pattern="^(positive|negative|boundary)$", description="positive | negative | boundary"),
    risk_level: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
    risk_score: Optional[float] = Query(None, ge=0.0, le=5.0),
    risk_description: Optional[str] = Query(None),
) -> AsyncTcJobResponse:
    """Génération asynchrone pour un plan de test. Suite optionnelle."""

    plan = await db.get(TestPlan, test_plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Test plan '{test_plan_id}' not found")

    job_id = f"{test_plan_id}-{test_suite_id or 'nosuite'}-{uuid4().hex}"

    job = {
        "job_id": job_id,
        "test_plan_id": test_plan_id,
        "test_suite_id": test_suite_id,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "risk_description": risk_description,
        "scenario_type": scenario_type,
    }

    try:
        await submit_tc_job(job)
    except Exception as exc:
        logger.exception("[TC_GEN_API] Failed to enqueue job for plan=%s", test_plan_id)
        raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {exc}")

    return AsyncTcJobResponse(
        job_id=job_id,
        test_plan_id=test_plan_id,
        test_suite_id=test_suite_id,
        status="queued",
    )


@router.get(
    "/generate/stream/{job_id}",
    summary="SSE stream for TC generation job",
)
async def stream_tc_job(request: Request, job_id: str):
    """Streaming des événements de génération via SSE."""
    return StreamingResponse(
        _tc_event_generator(job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# HELPERS
# ============================================================

async def _tc_event_generator(job_id: str, request: Request):
    """Générateur d'événements SSE pour un job de génération."""
    import json
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    connections.setdefault(job_id, []).append(queue)

    for msg in event_buffer.get(job_id, []):
        yield f"event: {msg['event']}\ndata: {json.dumps(msg['data'])}\n\n"
        if msg["event"] in ("tc_generated", "tc_failed"):
            connections[job_id].remove(queue)
            if not connections[job_id]:
                del connections[job_id]
            return

    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                message = await asyncio.wait_for(queue.get(), timeout=15)
                yield f"event: {message['event']}\ndata: {json.dumps(message['data'])}\n\n"
                if message["event"] in ("tc_generated", "tc_failed"):
                    break
            except asyncio.TimeoutError:
                yield "event: ping\ndata: {}\n\n"
    finally:
        if job_id in connections:
            try:
                connections[job_id].remove(queue)
            except ValueError:
                pass
            if not connections[job_id]:
                del connections[job_id]