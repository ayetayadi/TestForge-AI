import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, Enum as SqlEnum, Float, Integer, String, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import TestCaseResultStatus

if TYPE_CHECKING:
    from app.models.test_execution import TestExecution
    from app.models.test_case import TestCase
    from app.models.playwright_script_version import PlaywrightScriptVersion


class TestCaseResult(Base):
    """
    Résultat d'UN cas de test dans UNE TestExecution.

    Contient l'ordre d'exécution dans cette session (peut différer
    de l'ordre par défaut de la suite, car le testeur peut réordonner
    ou exclure des TCs pour chaque exécution).

    Les steps effectués sont stockés en JSON pour rester simple :
    [
      { "order": 1, "action": "navigate https://...", "status": "passed", "error": null },
      { "order": 2, "action": "click #login", "status": "failed", "error": "Element not found" }
    ]
    """
    __tablename__ = "test_case_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    execution_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    test_case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Version de script utilisée (traçabilité)
    script_version_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("playwright_script_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Ordre d'exécution DANS CETTE TestExecution (1, 2, 3...)
    execution_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # ==============================
    # STATUT & RÉSULTAT
    # ==============================

    status: Mapped[TestCaseResultStatus] = mapped_column(
        SqlEnum(TestCaseResultStatus),
        default=TestCaseResultStatus.SKIPPED,
        nullable=False,
    )

    # Steps effectués pendant l'exécution (JSON)
    steps: Mapped[List[dict]] = mapped_column(
        JSONB, default=list, nullable=False, server_default="[]"
    )

    # Justification / résumé court de l'agent
    justification: Mapped[Optional[str]] = mapped_column(Text)

    # Message d'erreur brut si status=failed/error
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Screenshot final (base64)
    screenshot_b64: Mapped[Optional[str]] = mapped_column(Text)

    # ==============================
    # MÉTRIQUES
    # ==============================

    duration: Mapped[Optional[float]] = mapped_column(Float)
    steps_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    steps_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ==============================
    # RELATIONS
    # ==============================

    execution: Mapped["TestExecution"] = relationship(
        "TestExecution", back_populates="test_case_results", foreign_keys=[execution_id]
    )

    test_case: Mapped["TestCase"] = relationship(
        "TestCase", foreign_keys=[test_case_id]
    )

    script_version: Mapped[Optional["PlaywrightScriptVersion"]] = relationship(
        "PlaywrightScriptVersion", foreign_keys=[script_version_id]
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_tc_result_execution_id", "execution_id"),
        Index("idx_tc_result_test_case_id", "test_case_id"),
        Index("idx_tc_result_status", "status"),
        Index("idx_tc_result_exec_order", "execution_id", "execution_order"),
    )
