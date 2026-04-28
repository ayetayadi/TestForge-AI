import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import DependencyType

if TYPE_CHECKING:
    from app.models.test_case import TestCase
    from app.models.test_plan import TestPlan


class TestCaseDependency(Base):
    """Arête du graphe de dépendances entre test cases.

    source → target : source doit s'exécuter avant target (REQUIRES),
                      ou source bloque target si échoue (BLOCKS).
    Le graphe est généré par l'IA puis ajustable manuellement.
    """
    __tablename__ = "test_case_dependencies"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Scoper le graphe à un test plan (optionnel)
    test_plan_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("test_plans.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )

    source_test_case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    target_test_case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    dependency_type: Mapped[str] = mapped_column(
        String(20), default=DependencyType.REQUIRES, nullable=False
    )

    is_ai_generated: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    is_manual_override: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ==============================
    # RELATIONS
    # ==============================

    source_test_case: Mapped["TestCase"] = relationship(
        "TestCase",
        back_populates="source_dependencies",
        foreign_keys=[source_test_case_id]
    )

    target_test_case: Mapped["TestCase"] = relationship(
        "TestCase",
        back_populates="target_dependencies",
        foreign_keys=[target_test_case_id]
    )

    test_plan: Mapped[Optional["TestPlan"]] = relationship(
        "TestPlan", back_populates="test_case_dependencies"
    )

    # ==============================
    # CONTRAINTES & INDEX
    # ==============================

    __table_args__ = (
        UniqueConstraint(
            "test_plan_id", "source_test_case_id", "target_test_case_id",
            name="uq_dependency_per_plan"
        ),
        Index("idx_dep_source", "source_test_case_id"),
        Index("idx_dep_target", "target_test_case_id"),
        Index("idx_dep_plan", "test_plan_id"),
    )
