import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.models.enums import TestSuiteStatus

if TYPE_CHECKING:
    from app.models.test_plan import TestPlan
    from app.models.test_case import TestCase


class TestSuite(Base):
    __tablename__ = "test_suites"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    test_plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    suite_type: Mapped[Optional[str]] = mapped_column(String(50))
    priority: Mapped[Optional[str]] = mapped_column(String(20))  # critical | high | medium | low
    is_ai_generated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    execution_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    risk_coverage_pct: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True,
        comment="Pourcentage de couverture des risques (0.0 à 1.0)"
    )
    
    risk_coverage_uncovered: Mapped[Optional[List[str]]] = mapped_column(
        JSONB, nullable=True, default=lambda: [],
        comment="IDs des risques non couverts"
    )
    
    mitigation_status: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, default="not_mitigated",
        comment="fully_mitigated | partially_mitigated | not_mitigated"
    )

    # For cross-cutting suites (smoke, regression, risk_based):
    # TC IDs are stored here instead of via FK (a TC can appear in multiple cross-cutting suites).
    tc_snapshot: Mapped[Optional[List[str]]] = mapped_column(
        JSONB, nullable=True,
        comment="TC IDs for smoke/regression/risk_based suites (not linked via FK)"
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=TestSuiteStatus.DRAFT,
        nullable=False,
        server_default=TestSuiteStatus.DRAFT
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ==============================
    # RELATIONS
    # ==============================

    test_plan: Mapped["TestPlan"] = relationship("TestPlan", back_populates="test_suites")

    # ondelete="SET NULL" on test_case_id — deleting a suite orphans its test cases
    # rather than cascading deletion
    test_cases: Mapped[List["TestCase"]] = relationship(
        "TestCase",
        back_populates="test_suite",
        foreign_keys="TestCase.test_suite_id"
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_test_suite_test_plan_id", "test_plan_id"),
        Index("idx_test_suite_status", "status"),
        Index("idx_test_suite_type", "suite_type"),
    )
