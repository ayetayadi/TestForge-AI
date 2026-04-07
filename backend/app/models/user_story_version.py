from datetime import datetime
import uuid
from typing import List, Optional

from sqlalchemy import DateTime, String, Text, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class UserStoryVersion(Base):
    __tablename__ = "user_story_versions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    user_story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_stories.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jobs.id"),
        nullable=False,
        index=True
    )

    improved_story: Mapped[str] = mapped_column(Text, nullable=False)

    acceptance_criteria: Mapped[List[str]] = mapped_column(
        JSONB,
        default=lambda: [],
        server_default="[]"
    )

    initial_score: Mapped[Optional[float]] = mapped_column(Float)
    final_score: Mapped[Optional[float]] = mapped_column(Float)

    iteration: Mapped[int] = mapped_column(default=0, nullable=False)

    llm_calls: Mapped[Optional[int]] = mapped_column(Integer)
    duration: Mapped[Optional[float]] = mapped_column(Float)

    is_selected: Mapped[bool] = mapped_column(default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )

    # =========================
    # RELATIONS
    # =========================
    user_story = relationship("UserStory", back_populates="versions", foreign_keys=[user_story_id])
    job = relationship("Job", back_populates="versions", foreign_keys=[job_id])

    __table_args__ = (
        Index("idx_version_user_story_id", "user_story_id"),
        Index("idx_version_job_id", "job_id"),
        Index("idx_version_selected", "is_selected"),
    )