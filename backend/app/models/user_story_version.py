from datetime import datetime
import uuid
from typing import List, Optional
from sqlalchemy import DateTime, String, Text, Float, ForeignKey, Index, Integer, Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import StoryDecision

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

    job_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("jobs.id"),
        nullable=True
    )

    improved_story: Mapped[str] = mapped_column(Text, nullable=False)

    generated_acceptance_criteria: Mapped[List[str]] = mapped_column(
        JSONB,
        default=lambda: [],
        server_default="[]"
    )

    # =========================
    # SCORES
    # =========================
    initial_score: Mapped[Optional[float]] = mapped_column(Float)
    final_score: Mapped[Optional[float]] = mapped_column(Float)
    iteration: Mapped[int] = mapped_column(default=0, nullable=False)

    # =========================
    # TESTABILITY
    # =========================
    testability_score: Mapped[Optional[float]] = mapped_column(Float)
    is_testable: Mapped[Optional[bool]] = mapped_column()
    testability_issues: Mapped[Optional[List[str]]] = mapped_column(JSONB)

    # =========================
    # DECISION
    # =========================
    decision_status: Mapped[StoryDecision] = mapped_column(
        SqlEnum(StoryDecision),
        default=StoryDecision.PENDING,
        nullable=False
    )

    # =========================
    # LLM METRICS
    # =========================
    llm_calls: Mapped[Optional[int]] = mapped_column(Integer)
    duration: Mapped[Optional[float]] = mapped_column(Float)

    model_used: Mapped[Optional[str]] = mapped_column(String(100))
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer)

    # =========================
    # META
    # =========================
    version_type: Mapped[Optional[str]] = mapped_column(String(50))  # initial / refined

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )

    # =========================
    # RELATIONS
    # =========================
    user_story = relationship(
        "UserStory", 
        back_populates="versions",
        foreign_keys=[user_story_id]
        )
    job = relationship("Job", back_populates="versions")

    __table_args__ = (
        Index("idx_version_user_story_id", "user_story_id"),
        Index("idx_version_job_id", "job_id"),
    )