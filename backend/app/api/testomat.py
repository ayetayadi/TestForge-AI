import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.repositories import testomat_repository as repo
from app.repositories.test_case_repository import get_test_cases_by_ids  # noqa: E501
from app.services import testomat_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/testomat", tags=["testomat"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class ConnectRequest(BaseModel):
    api_key: str


class PushRequest(BaseModel):
    test_case_ids: List[str]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await repo.get_connection(db, current_user.id)
    if not conn:
        return {"connected": False}
    return {
        "connected": True,
        "api_key_preview": conn.api_key_preview,
        "connected_at": conn.connected_at.isoformat(),
    }


@router.post("/connect")
async def connect(
    body: ConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API key is required")

    valid = await testomat_service.validate_api_key(api_key)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Testomat.io API key — please check your key and try again",
        )

    conn = await repo.save_connection(db, current_user.id, api_key)
    await db.commit()
    logger.info("[Testomat] User %s connected", current_user.id)
    return {
        "connected": True,
        "api_key_preview": conn.api_key_preview,
        "connected_at": conn.connected_at.isoformat(),
    }


@router.delete("/disconnect")
async def disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await repo.delete_connection(db, current_user.id)
    await db.commit()
    return {"connected": False}


@router.post("/push")
async def push_test_cases(
    body: PushRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await repo.get_connection(db, current_user.id)
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Testomat.io not connected — go to Integrations → Testomat to connect first",
        )

    if not body.test_case_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No test case IDs provided")

    test_cases = await get_test_cases_by_ids(db, body.test_case_ids)
    if not test_cases:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching test cases found")

    result = await testomat_service.push_test_cases_batch(conn.api_key, test_cases)

    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Testomat push failed: {result['error']}",
        )

    return {
        "pushed_count": result["pushed_count"],
        "total_requested": len(body.test_case_ids),
    }
