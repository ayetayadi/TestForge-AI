"""Test Suites API — list and detail with traceability matrix, dependency graph, prioritization."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.models.user import User
from app.services.test_suite_service import TestSuiteService
from app.schemas.test_suite_schema import (
    TestSuiteListResponse,
    TestSuiteDetailSchema,
    GenerateTestSuitesRequest,
    GenerateTestSuitesResponse,
    AssignTestCaseRequest,
    UnassignTestCaseRequest,
    UpdateTestSuiteRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test-suites", tags=["Test Suites"])


# ============================================================
# LIST
# ============================================================

@router.get(
    "/",
    response_model=TestSuiteListResponse,
    summary="List test suites",
    description="All test suites, optionally filtered by plan, project, type or status.",
)
async def list_test_suites(
    plan_id: Optional[str] = Query(None, description="Filter by test plan ID"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    suite_type: Optional[str] = Query(None, description="Filter by suite type (smoke, regression, etc.)"),
    status: Optional[str] = Query(None, description="Filter by status (draft, active, completed)"),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> TestSuiteListResponse:
    from app.api.deps import get_user_project_ids
    project_ids = await get_user_project_ids(db, current_user.id)
    service = TestSuiteService(db)
    return await service.get_all(
        plan_id=plan_id,
        project_id=project_id,
        suite_type=suite_type,
        status=status,
        project_ids=project_ids,
    )


# ============================================================
# DETAIL
# ============================================================

@router.get(
    "/{suite_id}",
    response_model=TestSuiteDetailSchema,
    summary="Test suite detail with full QA context",
    description=(
        "Returns a test suite with: test plan context, risk analysis summary, "
        "test cases sorted by risk→coverage→AC priority, traceability matrix "
        "(Story × AC × Test Cases), dependency graph (nodes + edges + topological order), "
        "priority reasoning, all suites execution order, and QA lifecycle timeline."
    ),
)
async def get_test_suite(
    suite_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> TestSuiteDetailSchema:
    service = TestSuiteService(db)
    detail = await service.get_detail(suite_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Test suite '{suite_id}' not found")
    return detail


# ============================================================
# GENERATE SUITES (AI)
# ============================================================

@router.post(
    "/generate",
    status_code=201,
    response_model=GenerateTestSuitesResponse,
    summary="Generate test suites from test cases",
    description=(
        "Launches the test suite organization pipeline. "
        "Groups unassigned test cases by the chosen strategy and creates suites. "
        "Strategies: risk_level, test_type, feature, mixed."
    ),
)
async def generate_test_suites(
    request: GenerateTestSuitesRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> GenerateTestSuitesResponse:
    service = TestSuiteService(db)
    try:
        result = await service.generate_suites(
            test_plan_id=request.test_plan_id,
            project_name=request.project_name,
        )
        return GenerateTestSuitesResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"[SUITE GEN] Unexpected error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Suite generation failed: {str(exc)}")


# ============================================================
# ASSIGN TEST CASE TO SUITE
# ============================================================
@router.post(
    "/{suite_id}/assign",
    status_code=200,
    summary="Assign a test case to this suite",
    description="Manually assign a test case to a test suite.",
)
async def assign_test_case(
    suite_id: str,
    request: AssignTestCaseRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    service = TestSuiteService(db)

    from app.repositories.test_suite_repository import TestSuiteRepository
    repo = TestSuiteRepository(db)
    suite = await repo.get_by_id(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail=f"Test suite '{suite_id}' not found")
    
    success = await service.assign_test_case_to_suite(
        test_case_id=request.test_case_id,
        suite_id=suite_id,
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Test case or suite not found")
    
    return {"status": "success", "message": f"Test case assigned to suite '{suite_id}'"}

# ============================================================
# UNASSIGN TEST CASE FROM SUITE
# ============================================================

@router.post(
    "/{suite_id}/unassign",
    status_code=200,
    summary="Remove a test case from this suite",
    description="Unassign a test case from its test suite.",
)
async def unassign_test_case(
    suite_id: str,
    request: UnassignTestCaseRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    service = TestSuiteService(db)
    
    success = await service.unassign_test_case_from_suite(
        test_case_id=request.test_case_id,
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Test case not found")
    
    return {"status": "success", "message": "Test case unassigned from suite"}


# ============================================================
# UPDATE SUITE
# ============================================================

@router.put(
    "/{suite_id}",
    response_model=TestSuiteDetailSchema,
    summary="Update test suite",
    description="Update test suite metadata (title, description, priority, status, etc.).",
)
async def update_test_suite(
    suite_id: str,
    request: UpdateTestSuiteRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> TestSuiteDetailSchema:
    from app.repositories.test_suite_repository import TestSuiteRepository
    
    repo = TestSuiteRepository(db)
    
    # Build update data (only non-None fields)
    update_data = request.model_dump(exclude_none=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    suite = await repo.get_by_id(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail=f"Test suite '{suite_id}' not found")
    
    for key, value in update_data.items():
        setattr(suite, key, value)
    
    await db.commit()
    await db.refresh(suite)
    
    service = TestSuiteService(db)
    detail = await service.get_detail(suite_id)
    return detail


# ============================================================
# DELETE SUITE
# ============================================================

@router.delete(
    "/{suite_id}",
    status_code=200,
    summary="Delete test suite",
    description="Delete a test suite. Test cases become unassigned (not deleted).",
)
async def delete_test_suite(
    suite_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    from app.repositories.test_suite_repository import TestSuiteRepository
    
    repo = TestSuiteRepository(db)
    
    suite = await repo.get_by_id(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail=f"Test suite '{suite_id}' not found")
    
    # Unassign all test cases from this suite
    for tc in (suite.test_cases or []):
        tc.test_suite_id = None
    
    await db.delete(suite)
    await db.commit()
    
    return {"status": "success", "message": f"Test suite '{suite_id}' deleted"}


# ============================================================
# GET TRACEABILITY MATRIX FOR PLAN
# ============================================================

@router.get(
    "/traceability/{plan_id}",
    summary="Get traceability matrix for a test plan",
    description="Returns the full traceability matrix: Stories × ACs × Test Cases with coverage metrics.",
)
async def get_traceability_matrix(
    plan_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    from app.repositories.test_suite_repository import get_traceability_matrix as repo_get_matrix
    
    matrix = await repo_get_matrix(db, plan_id)
    return matrix

# ============================================================
# GET DEPENDENCY GRAPH FOR PLAN
# ============================================================

@router.get(
    "/dependencies/{plan_id}",
    summary="Get dependency graph for a test plan",
    description="Returns the dependency graph with nodes, edges, and topological execution order.",
)
async def get_dependency_graph(
    plan_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
):
    from app.repositories.test_suite_repository import get_dependencies_for_plan as repo_get_deps
    from app.repositories.test_case_repository import get_test_cases_by_test_plan_id
    
    dependencies = await repo_get_deps(db, plan_id)
    test_cases = await get_test_cases_by_test_plan_id(db, plan_id)
    
    # Build graph
    service = TestSuiteService(db)
    graph = service._build_dependency_graph(test_cases, dependencies)
    
    return graph.model_dump()
