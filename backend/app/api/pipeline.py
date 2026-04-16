from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.services.pipeline_service import run_pipeline

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class RunPipelineRequest(BaseModel):
    issue_keys: Optional[List[str]] = None
    project_id: Optional[str] = None


@router.post("/run")
async def run_pipeline_route(
    request: RunPipelineRequest,
    db: AsyncSession = Depends(get_db)
):
    try:
        result = await run_pipeline(
            db,
            request.issue_keys,
            request.project_id
        )

        return {"message": "Pipeline started", **result}

    except ValueError as e:
        raise HTTPException(400, str(e))

    except Exception as e:
        raise HTTPException(500, str(e))