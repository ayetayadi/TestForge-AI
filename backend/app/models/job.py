import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class Job(Base):
    """
    Persistent job record for async worker tasks.

    Replaces in-memory asyncio.Queue tracking — jobs survive restarts
    and can be re-queued on startup (status='pending').

    Job types: tc_generation | risk_analysis | us_refinement
    Statuses:  pending → running → completed | failed
    """
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    job_type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )

    # Input parameters for the worker (test_plan_id, user_story_id, filters…)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Summary written by worker on completion (counts, coverage, etc.)
    result_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # SSE channel identifier for real-time progress streaming
    sse_job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_job_type_status", "job_type", "status"),
        Index("idx_job_created_at", "created_at"),
    )
