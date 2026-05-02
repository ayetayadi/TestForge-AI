"""Test Plan API — generation, validation, export, sharing."""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.models.user import User
from app.schemas.test_plan_schema import (
    GenerateTestPlanRequest,
    GenerateTestPlanResponse,
    TestPlanResponse,
    TestPlanListResponse,
    TestPlanUpdate,
    SendEmailRequest,
    GenerateEmailBodyRequest,
    GenerateEmailBodyResponse,
    JiraNotificationRequest,
    JiraNotificationResponse,
)
from app.services.test_plan_service import TestPlanService
from app.services.test_plan_export_service import TestPlanExportService
from app.repositories.test_plan_repository import TestPlanRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test-plans", tags=["Test Plans"])


# ============================================================
# AI GENERATION
# ============================================================

@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    response_model=GenerateTestPlanResponse,
    summary="Generate AI test plan draft",
    description=(
        "Generates a complete ISTQB-compliant test plan draft using AI, "
        "based on existing accepted risk analysis results. "
        "Supports filtering by sprint/epic. "
        "The plan is created with status 'ai_proposed' awaiting QA validation."
    ),
)
async def generate_test_plan(
    request: GenerateTestPlanRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> GenerateTestPlanResponse:
    service = TestPlanService(db)
    print(f"📦 Received: {request.model_dump()}")
    try:
        return await service.generate_ai_draft(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"[API] Test plan generation failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Test plan generation failed. Please try again.",
        )


@router.post(
    "/{plan_id}/regenerate",
    status_code=status.HTTP_200_OK,
    response_model=GenerateTestPlanResponse,
    summary="Regenerate AI draft",
)
async def regenerate_test_plan(
    plan_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> GenerateTestPlanResponse:
    service = TestPlanService(db)
    try:
        return await service.regenerate_ai_draft(plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"[API] Regeneration failed for {plan_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ============================================================
# CRUD
# ============================================================

@router.get(
    "/project/{project_id}",
    response_model=TestPlanListResponse,
    summary="List test plans for a project",
    description="Supports filtering by sprint and epic.",
)
async def get_project_test_plans(
    project_id: str,
    sprint_ids: Optional[str] = Query(None, description="Comma-separated sprint IDs"),
    epic_keys: Optional[str] = Query(None, description="Comma-separated epic keys"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> TestPlanListResponse:
    service = TestPlanService(db)
    
    sprint_list = sprint_ids.split(',') if sprint_ids else None
    epic_list = epic_keys.split(',') if epic_keys else None
    
    return await service.get_test_plans_by_project(
        project_id=project_id,
        sprint_ids=sprint_list,
        epic_keys=epic_list,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/all",
    response_model=TestPlanListResponse,
    summary="Get all test plans with optional filters",
)
async def get_all_test_plans(
    project_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="draft | ai_proposed | approved"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> TestPlanListResponse:
    service = TestPlanService(db)
    return await service.get_all_test_plans(
        project_id=project_id,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/project/{project_id}/summary",
    summary="Get test plan statistics for a project",
)
async def get_project_summary(
    project_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    service = TestPlanService(db)
    return await service.get_summary_by_project(project_id)


@router.get(
    "/{plan_id}",
    response_model=TestPlanResponse,
    summary="Get a test plan by ID",
)
async def get_test_plan(
    plan_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> TestPlanResponse:
    service = TestPlanService(db)
    plan = await service.get_test_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test plan not found")
    return plan


@router.put(
    "/{plan_id}",
    response_model=TestPlanResponse,
    summary="Update / edit a test plan",
)
async def update_test_plan(
    plan_id: str,
    data: TestPlanUpdate,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> TestPlanResponse:
    service = TestPlanService(db)
    plan = await service.update_test_plan(plan_id, data)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test plan not found")
    return plan


@router.delete(
    "/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a test plan",
)
async def delete_test_plan(
    plan_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> None:
    service = TestPlanService(db)
    deleted = await service.delete_test_plan(plan_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test plan not found")


@router.delete(
    "/project/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete all test plans for a project",
)
async def delete_project_test_plans(
    project_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> None:
    """Delete all test plans associated with a project."""
    service = TestPlanService(db)
    await service.delete_test_plans_by_project(project_id)


# ============================================================
# APPROVAL WORKFLOW
# ============================================================

@router.post(
    "/{plan_id}/approve",
    response_model=TestPlanResponse,
    summary="Approve AI test plan draft",
)
async def approve_test_plan(
    plan_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> TestPlanResponse:
    service = TestPlanService(db)
    try:
        return await service.approve_test_plan(plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/{plan_id}/reject",
    response_model=TestPlanResponse,
    summary="Reject AI draft — reset to draft",
)
async def reject_test_plan(
    plan_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> TestPlanResponse:
    service = TestPlanService(db)
    try:
        return await service.reject_test_plan(plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ============================================================
# EXPORT 
# ============================================================

@router.get(
    "/{plan_id}/export/pdf",
    summary="Export test plan as PDF",
    responses={200: {"content": {"application/pdf": {}}, "description": "PDF file download"}},
)
async def export_pdf(
    plan_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Response:
    repo = TestPlanRepository(db)
    plan = await repo.get_by_id(plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test plan not found")

    try:
        exporter = TestPlanExportService()
        pdf_bytes = exporter.export_pdf(plan)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))
    except Exception as exc:
        logger.error(f"[API] PDF export failed for {plan_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="PDF generation failed.")

    filename = f"test_plan_{plan_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{plan_id}/export/docx",
    summary="Export test plan as DOCX",
    responses={200: {"content": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}}, "description": "DOCX file download"}},
)
async def export_docx(
    plan_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Response:
    repo = TestPlanRepository(db)
    plan = await repo.get_by_id(plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test plan not found")

    try:
        exporter = TestPlanExportService()
        docx_bytes = exporter.export_docx(plan)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))
    except Exception as exc:
        logger.error(f"[API] DOCX export failed for {plan_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="DOCX generation failed.")

    filename = f"test_plan_{plan_id[:8]}.docx"
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return Response(
        content=docx_bytes,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================
# EMAIL SHARING 
# ============================================================

@router.post(
    "/{plan_id}/email/generate-body",
    response_model=GenerateEmailBodyResponse,
    summary="AI-generate email subject + body",
)
async def generate_email_body(
    plan_id: str,
    request: GenerateEmailBodyRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> GenerateEmailBodyResponse:
    service = TestPlanService(db)
    try:
        return await service.generate_email_body(plan_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"[API] Email body generation failed: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Email body generation failed.")


@router.post(
    "/{plan_id}/email/send",
    summary="Send test plan report via email",
)
async def send_email(
    plan_id: str,
    request: SendEmailRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    service = TestPlanService(db)
    try:
        return await service.send_email(plan_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.error(f"[API] Email send failed: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to send email: {exc}")


# ============================================================
# JIRA NOTIFICATION 
# ============================================================

@router.post(
    "/{plan_id}/jira/notify",
    response_model=JiraNotificationResponse,
    summary="Create Jira ticket for test plan",
)
async def send_jira_notification(
    plan_id: str,
    request: JiraNotificationRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> JiraNotificationResponse:
    service = TestPlanService(db)
    try:
        return await service.send_jira_notification(plan_id, request, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[API] Jira notification failed: {exc}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create Jira ticket: {exc}")