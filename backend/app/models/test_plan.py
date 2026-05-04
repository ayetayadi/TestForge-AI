# models/test_plan.py

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import TestPlanStatus

if TYPE_CHECKING:
    from app.models.jira_project import JiraProject
    from app.models.test_suite import TestSuite


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
    scope_type: Mapped[Optional[str]] = mapped_column(String(50))
    scope_refs: Mapped[List[str]] = mapped_column(JSONB, default=lambda: [], server_default="[]")
    in_scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    out_of_scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    test_types: Mapped[List[str]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]", nullable=False
    )
    test_levels: Mapped[List[str]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]", nullable=False
    )
    environment: Mapped[Optional[str]] = mapped_column(String(100))
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
    risk_analysis: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    estimation: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    recommendations_detail: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # ==============================
    # 🔥 NOUVEAU : Business Flow Order (LLM-determined)
    # ==============================
    
    business_flow_order: Mapped[Optional[dict]] = mapped_column(
        JSONB, 
        nullable=True,
        comment="LLM-determined business flow execution order {flow: rank}"
    )
    
    tc_classifications: Mapped[Optional[dict]] = mapped_column(
        JSONB, 
        nullable=True,
        comment="LLM-determined test case classifications {tc_code: {business_flow, risk_level, reasoning}}"
    )
    
    flow_reasoning: Mapped[Optional[str]] = mapped_column(
        Text, 
        nullable=True,
        comment="LLM reasoning for the business flow order"
    )
    
    flow_details: Mapped[Optional[dict]] = mapped_column(
        JSONB, 
        nullable=True,
        comment="LLM flow details {flow: {tc_count, risk_breakdown, reason}}"
    )
    
    project_context_summary: Mapped[Optional[str]] = mapped_column(
        Text, 
        nullable=True,
        comment="LLM summary of project context analyzed"
    )

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
        "TestSuite", back_populates="test_plan", cascade="all, delete-orphan"
    )

    test_cases: Mapped[List["TestCase"]] = relationship(
        "TestCase", back_populates="test_plan", foreign_keys="TestCase.test_plan_id",
        cascade="all, delete-orphan"
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_test_plan_project_id", "project_id"),
        Index("idx_test_plan_status", "status"),
    )