import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import DateTime, Enum as SqlEnum, Float, Integer, String, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import TestResultStatus

if TYPE_CHECKING:
    from app.models.test_run import TestRun


class TestResult(Base):
    """
    Résumé du résultat d'un TestRun.
    Un TestRun a exactement un TestResult (relation 1-1).
    Le détail step-by-step est dans TestStepResult.
    """
    __tablename__ = "test_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    test_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True
    )

    # ==============================
    # RÉSULTAT
    # ==============================

    status: Mapped[TestResultStatus] = mapped_column(
        SqlEnum(TestResultStatus),
        nullable=False
    )

    # Explication générée par l'agent (ex: "Login réussi, redirection /dashboard confirmée")
    justification: Mapped[Optional[str]] = mapped_column(Text)

    # Message d'erreur brut si status=error
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Screenshot final (base64) — capturé à la fin ou sur échec
    screenshot_b64: Mapped[Optional[str]] = mapped_column(Text)

    # ==============================
    # MÉTRIQUES
    # ==============================

    duration: Mapped[Optional[float]] = mapped_column(Float)

    # Nombre total de steps ReAct exécutés
    step_count: Mapped[Optional[int]] = mapped_column(Integer)

    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ==============================
    # RELATION
    # ==============================

    test_run: Mapped["TestRun"] = relationship(
        "TestRun", back_populates="result"
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_test_result_test_run_id", "test_run_id"),
        Index("idx_test_result_status", "status"),
    )
