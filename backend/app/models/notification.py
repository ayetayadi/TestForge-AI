import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Context (both optional so we can have global or project-scoped notifications)
    project_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    issue_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Payload
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Types: story_added | story_updated | story_deleted
    #        quality_issue | ambiguous_story
    #        story_approved | story_refined

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    # Severities: info | warning | error

    # State
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jira_comment_posted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_notif_project_key", "project_key"),
        Index("idx_notif_type", "type"),
        Index("idx_notif_is_read", "is_read"),
    )
