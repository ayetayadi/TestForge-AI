import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import DateTime, Enum as SqlEnum, Float, Integer, String, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import StepType, StepStatus

if TYPE_CHECKING:
    from app.models.test_run import TestRun


class TestStepResult(Base):
    """
    Un step individuel du ReAct loop pour un TestRun.
    Chaque think/act/observe est une ligne → queryable, debuggable, retryable.
    """
    __tablename__ = "test_step_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    test_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Ordre d'exécution dans le run (1, 2, 3...)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # think | act | observe
    step_type: Mapped[StepType] = mapped_column(
        SqlEnum(StepType), nullable=False
    )

    # ==============================
    # CONTENU DU STEP
    # ==============================

    # THINK → raisonnement de l'agent
    # ACT   → description de l'action
    # OBSERVE → résumé de l'observation
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Rempli uniquement si step_type=act
    # "browser_navigate" | "browser_fill" | "browser_click" | ...
    tool_name: Mapped[Optional[str]] = mapped_column(String(100))

    # Arguments passés au tool: {"url": "https://..."} | {"selector": "#email", "value": "..."}
    tool_args: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Résultat retourné par le tool MCP
    tool_result: Mapped[Optional[dict]] = mapped_column(JSONB)

    # ==============================
    # STATUT & MÉTRIQUES
    # ==============================

    status: Mapped[StepStatus] = mapped_column(
        SqlEnum(StepStatus),
        default=StepStatus.SUCCESS,
        nullable=False
    )

    # Temps d'exécution du step en secondes
    duration: Mapped[Optional[float]] = mapped_column(Float)

    # Screenshot capturé après ce step (base64) — utile pour debugging
    screenshot_b64: Mapped[Optional[str]] = mapped_column(Text)

    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ==============================
    # RELATION
    # ==============================

    test_run: Mapped["TestRun"] = relationship(
        "TestRun", back_populates="steps"
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_step_result_test_run_id", "test_run_id"),
        Index("idx_step_result_order", "test_run_id", "step_order"),
        Index("idx_step_result_type", "test_run_id", "step_type"),
        Index("idx_step_result_status", "status"),
    )
