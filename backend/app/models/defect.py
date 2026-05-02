from datetime import datetime
import uuid
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, Index, String, Text, ForeignKey, Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import DefectSeverity, DefectStatus

if TYPE_CHECKING:
    from app.models.user_story import UserStory
    from app.models.user_story_version import UserStoryVersion
    from app.models.test_case import TestCase


class Defect(Base):
    __tablename__ = "defects"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    # ========================
    # CLÉS ÉTRANGÈRES
    # ========================

    user_story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_stories.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    user_story_version_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("user_story_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Test case qui a révélé ce défaut (section 5.5)
    test_case_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("test_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # ========================
    # CONTENU DU DÉFAUT
    # ========================

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    severity: Mapped[DefectSeverity] = mapped_column(
        SqlEnum(DefectSeverity),
        default=DefectSeverity.HIGH,
        nullable=False
    )

    # Priorité de correction : critical | high | medium | low
    correction_priority: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    status: Mapped[DefectStatus] = mapped_column(
        SqlEnum(DefectStatus),
        default=DefectStatus.OPEN,
        nullable=False
    )

    # Étapes pour reproduire le défaut (section 5.5)
    reproduction_steps: Mapped[List[str]] = mapped_column(
        JSONB,
        default=lambda: [],
        server_default="[]"
    )

    # Issues détectées par l'IA qui ont déclenché ce défaut (pipeline de raffinement)
    detected_issues: Mapped[List[str]] = mapped_column(
        JSONB,
        default=lambda: [],
        server_default="[]"
    )

    # Capture d'écran en base64 (section 5.5)
    screenshot_b64: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Logs bruts (section 5.5)
    logs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Score au moment de la détection (pipeline IA)
    initial_score: Mapped[Optional[float]] = mapped_column()

    # ========================
    # JIRA TICKET
    # ========================
    jira_issue_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    jira_project_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # ========================
    # META
    # ========================
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

    # ========================
    # RELATIONS
    # ========================

    user_story: Mapped["UserStory"] = relationship(
        "UserStory",
        back_populates="defects",
        foreign_keys=[user_story_id]
    )

    user_story_version: Mapped[Optional["UserStoryVersion"]] = relationship(
        "UserStoryVersion",
        back_populates="defects",
        foreign_keys=[user_story_version_id]
    )

    test_case: Mapped[Optional["TestCase"]] = relationship(
        "TestCase",
        back_populates="defects",
        foreign_keys=[test_case_id]
    )

    # ========================
    # INDEXES
    # ========================
    __table_args__ = (
        Index("idx_defect_user_story_id", "user_story_id"),
        Index("idx_defect_test_case_id", "test_case_id"),
        Index("idx_defect_status", "status"),
        Index("idx_defect_severity", "severity"),
        Index("idx_defect_jira_issue_key", "jira_issue_key"),
    )
