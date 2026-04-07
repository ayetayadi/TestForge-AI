from datetime import datetime
import uuid
from typing import List, Optional

from sqlalchemy import DateTime, String, Text, Float, ForeignKey, Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import StoryDecision


class UserStory(Base):
    __tablename__ = "user_stories"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jira_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    issue_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    acceptance_criteria: Mapped[List[str]] = mapped_column(
        JSONB,
        default=lambda: [],
        server_default="[]"
    )

    issue_type: Mapped[Optional[str]] = mapped_column(String(50))
    priority: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[Optional[str]] = mapped_column(String(50))
    story_points: Mapped[Optional[float]] = mapped_column(Float)

    assignee: Mapped[Optional[str]] = mapped_column(String(200))
    reporter: Mapped[Optional[str]] = mapped_column(String(200))

    epic_key: Mapped[Optional[str]] = mapped_column(String(100))
    sprint: Mapped[Optional[str]] = mapped_column(String(200))

    labels: Mapped[List[str]] = mapped_column(
        JSONB,
        default=lambda: [],
        server_default="[]"
    )

    components: Mapped[List[str]] = mapped_column(
        JSONB,
        default=lambda: [],
        server_default="[]"
    )

    fix_version: Mapped[Optional[str]] = mapped_column(String(100))

    # =========================
    # DECISION
    # =========================

    decision_status: Mapped[StoryDecision] = mapped_column(
        SqlEnum(StoryDecision),
        default=StoryDecision.PENDING,
        nullable=False
    )

    jira_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    jira_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    # =========================
    # RELATIONS
    # =========================
    jira_project = relationship("JiraProject", back_populates="user_stories")

    versions = relationship(
        "UserStoryVersion",
        back_populates="user_story",
        cascade="all, delete-orphan",
        foreign_keys="UserStoryVersion.user_story_id"
    )

    jobs = relationship(
        "Job",
        back_populates="user_story",
        cascade="all, delete-orphan"
    )