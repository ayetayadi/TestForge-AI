import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import TestExecutionStatus

if TYPE_CHECKING:
    from app.models.test_case import TestCase
    from app.models.test_plan import TestPlan
    from app.models.defect import Defect


class TestExecution(Base):
    """Enregistrement d'une exécution manuelle d'un cas de test (section 5.5 ISTQB).

    Distinct de TestRun (exécution Playwright automatisée).
    Un testeur exécute un test, enregistre PASS/FAIL/SKIP/BLOCKED,
    et peut signaler un défaut en cas d'échec.
    """
    __tablename__ = "test_executions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    test_case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Plan auquel appartient cette session d'exécution (optionnel)
    test_plan_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("test_plans.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    # ==============================
    # RÉSULTAT
    # ==============================

    # pass | fail | skip | blocked
    result: Mapped[TestExecutionStatus] = mapped_column(
        String(20),
        nullable=False
    )

    # Nom ou email du testeur qui a exécuté
    executed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Notes libres du testeur
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ==============================
    # RELATIONS
    # ==============================

    test_case: Mapped["TestCase"] = relationship(
        "TestCase", back_populates="executions", foreign_keys=[test_case_id]
    )

    test_plan: Mapped[Optional["TestPlan"]] = relationship(
        "TestPlan", back_populates="test_executions", foreign_keys=[test_plan_id]
    )

    # Défaut signalé lors de cette exécution (0 ou 1 par exécution)
    defect: Mapped[Optional["Defect"]] = relationship(
        "Defect",
        back_populates="test_execution",
        foreign_keys="Defect.test_execution_id",
        uselist=False
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_test_execution_test_case_id", "test_case_id"),
        Index("idx_test_execution_test_plan_id", "test_plan_id"),
        Index("idx_test_execution_result", "result"),
        Index("idx_test_execution_executed_at", "executed_at"),
    )
