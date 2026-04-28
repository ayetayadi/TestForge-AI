import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import TestPlanStatus

if TYPE_CHECKING:
    from app.models.jira_project import JiraProject
    from app.models.test_suite import TestSuite
    from app.models.risk import Risk
    from app.models.test_case_dependency import TestCaseDependency
    from app.models.test_execution import TestExecution


class TestPlan(Base):
    __tablename__ = "test_plans"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jira_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # ==============================
    # CHAMPS TESTEUR (saisie manuelle)
    # ==============================

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    objective: Mapped[Optional[str]] = mapped_column(Text)
    scope_type: Mapped[Optional[str]] = mapped_column(String(50))# epic | sprint | release | manual | spec_document
    scope_refs: Mapped[List[str]] = mapped_column(JSONB, default=lambda: [], server_default="[]")# Ex: ["SCRUM-12", "SCRUM-13"] ou ["Sprint 4"]
    in_scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    out_of_scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    test_types: Mapped[List[str]] = mapped_column(
        JSONB,
        default=lambda: [],
        server_default="[]",
        nullable=False,
    )
    # functional | regression | smoke | security | performance | e2e | api

    test_levels: Mapped[List[str]] = mapped_column(
        JSONB,
        default=lambda: [],
        server_default="[]",
        nullable=False,
    )
    # component | integration | system | acceptance | e2e
    
    environment: Mapped[Optional[str]] = mapped_column(String(100)) # dev | staging | prod | uat

    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)

    entry_criteria: Mapped[Optional[str]] = mapped_column(Text)
    exit_criteria: Mapped[Optional[str]] = mapped_column(Text)

    # ==============================
    # CHAMPS IA (brouillon proposé)
    # ==============================

    approach: Mapped[Optional[str]] = mapped_column(Text)
    assumptions: Mapped[Optional[str]] = mapped_column(Text)
    constraints: Mapped[Optional[str]] = mapped_column(Text)

    stakeholders: Mapped[Optional[str]] = mapped_column(Text)
    communication: Mapped[Optional[str]] = mapped_column(Text)

    # ==============================
    # SNAPSHOTS CALCULÉS AUTOMATIQUEMENT
    # ==============================

    # Matrice de traçabilité : {us_id → [tc_id, ...]}
    matrix_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB)
    # Couverture : {total_us, covered_us, total_ac, covered_ac, coverage_pct}
    coverage_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB)

    # ==============================
    # STATUT & TRACKING
    # ==============================

    status: Mapped[str] = mapped_column(
        String(20),
        default=TestPlanStatus.DRAFT,
        nullable=False,
        server_default=TestPlanStatus.DRAFT
    )

    ai_draft_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    generation_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ==============================
    # RELATIONS
    # ==============================

    jira_project: Mapped["JiraProject"] = relationship("JiraProject", back_populates="test_plans")

    test_suites: Mapped[List["TestSuite"]] = relationship(
        "TestSuite",
        back_populates="test_plan",
        cascade="all, delete-orphan"
    )

    risks: Mapped[List["Risk"]] = relationship(
        "Risk",
        back_populates="test_plan",
        order_by="Risk.risk_score.desc()",
    )

    # Graphe de dépendances scopé à ce plan
    test_case_dependencies: Mapped[List["TestCaseDependency"]] = relationship(
        "TestCaseDependency",
        back_populates="test_plan",
        cascade="all, delete-orphan"
    )

    # Exécutions manuelles des tests de ce plan (section 5.5)
    test_executions: Mapped[List["TestExecution"]] = relationship(
        "TestExecution",
        back_populates="test_plan",
        cascade="all, delete-orphan"
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_test_plan_project_id", "project_id"),
        Index("idx_test_plan_status", "status"),
    )
