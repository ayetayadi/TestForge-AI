import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.test_plan import TestPlan
    from app.models.user_story import UserStory
    from app.models.jira_project import JiraProject


class Risk(Base):
    __tablename__ = "risks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jira_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    test_plan_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("test_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    user_story_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("user_stories.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # ── TRACABILITÉ DE LA SOURCE ──────────────────────
    source: Mapped[Optional[str]] = mapped_column(
        String(20), default="original", nullable=True
    )  # "original" | "approved_version"

    source_version_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )  # ID de la UserStoryVersion utilisée

    source_story_text: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Texte exact utilisé (improved_story OU title + description)

    source_acceptance_criteria: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON string des ACs utilisés pour l'analyse

    # ── RÉSULTAT DE L'ANALYSE ────────────────────────
    description: Mapped[str] = mapped_column(Text, nullable=False)
    mitigation: Mapped[Optional[str]] = mapped_column(Text)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    probability: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    impact: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=1.5, nullable=False)
    level: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)

    is_ai_generated: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    is_accepted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ==============================
    # RELATIONS
    # ==============================
    jira_project: Mapped["JiraProject"] = relationship("JiraProject", back_populates="risks")
    test_plan: Mapped[Optional["TestPlan"]] = relationship("TestPlan", back_populates="risks")
    user_story: Mapped[Optional["UserStory"]] = relationship("UserStory", back_populates="risks")

    # ==============================
    # COMPUTED PROPERTIES
    # ==============================
    @property
    def user_story_key(self) -> Optional[str]:
        return self.user_story.issue_key if self.user_story else None

    @property
    def user_story_title(self) -> Optional[str]:
        return self.user_story.title if self.user_story else None

    @property
    def parsed_acceptance_criteria(self) -> list[str]:
        """Désérialise les ACs stockés en JSON."""
        import json
        if not self.source_acceptance_criteria:
            return []
        try:
            return json.loads(self.source_acceptance_criteria)
        except (json.JSONDecodeError, TypeError):
            return []

    # ==============================
    # INDEX
    # ==============================
    __table_args__ = (
        Index("idx_risk_project_id", "project_id"),
        Index("idx_risk_plan_id", "test_plan_id"),
        Index("idx_risk_user_story_id", "user_story_id"),
        Index("idx_risk_level", "level"),
        Index("idx_risk_score", "risk_score"),
    )