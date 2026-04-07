from datetime import datetime
import uuid
from typing import Optional

from sqlalchemy import DateTime, String, Float, ForeignKey, Text, Enum as SqlEnum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import JobPhase, JobStatus


class Job(Base):
    __tablename__ = "jobs"

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

    # =========================
    # EXECUTION STATE
    # =========================
    status: Mapped[JobStatus] = mapped_column(
        SqlEnum(JobStatus),
        default=JobStatus.PROCESSING,
        nullable=False
    )

    phase: Mapped[Optional[JobPhase]] = mapped_column(
        SqlEnum(JobPhase),
        nullable=True
    )

    iteration: Mapped[int] = mapped_column(default=0)

    initial_score: Mapped[Optional[float]] = mapped_column(Float)
    final_score: Mapped[Optional[float]] = mapped_column(Float)

    error: Mapped[Optional[str]] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # =========================
    # RELATIONS
    # =========================
    user_story = relationship("UserStory", back_populates="jobs")

    versions = relationship(
        "UserStoryVersion",
        back_populates="job",
        cascade="all, delete-orphan"
    )