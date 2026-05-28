import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Float, Integer, String, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import TestExecutionStatus

if TYPE_CHECKING:
    from app.models.test_suite import TestSuite
    from app.models.test_case_result import TestCaseResult


class TestExecution(Base):
    """
    Une exécution complète d'une TestSuite.

    Une TestSuite peut être lancée plusieurs fois (1 → *).
    Chaque TestExecution regroupe les TestCaseResult des cas de test
    exécutés dans cette session (avec leur ordre et exclusions propres).
    """
    __tablename__ = "test_executions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    suite_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ==============================
    # CONFIGURATION
    # ==============================

    app_url: Mapped[str] = mapped_column(String(500), nullable=False)
    browser: Mapped[str] = mapped_column(
        String(50), default="chromium", nullable=False, server_default="chromium"
    )
    headless: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    stop_on_failure: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    model_id: Mapped[Optional[str]] = mapped_column(String(100))

    # ==============================
    # STATUT GLOBAL
    # ==============================

    status: Mapped[TestExecutionStatus] = mapped_column(
        SqlEnum(TestExecutionStatus),
        default=TestExecutionStatus.RUNNING,
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration: Mapped[Optional[float]] = mapped_column(Float)

    # ==============================
    # COMPTEURS
    # ==============================

    total_count:   Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    passed_count:  Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    failed_count:  Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    error_count:   Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")

    # Lance par (utilisateur)
    triggered_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ==============================
    # RELATIONS
    # ==============================

    suite: Mapped["TestSuite"] = relationship(
        "TestSuite", foreign_keys=[suite_id]
    )

    test_case_results: Mapped[List["TestCaseResult"]] = relationship(
        "TestCaseResult",
        back_populates="execution",
        cascade="all, delete-orphan",
        order_by="TestCaseResult.execution_order",
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_test_execution_suite_id", "suite_id"),
        Index("idx_test_execution_status", "status"),
        Index("idx_test_execution_started_at", "started_at"),
    )
