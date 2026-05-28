import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Integer, String, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import ScriptValidationStatus, ScriptSource

if TYPE_CHECKING:
    from app.models.test_case import TestCase


class PlaywrightScriptVersion(Base):
    """
    Version d'un script Playwright pour un TestCase.
    Chaque édition manuelle ou regénération crée une nouvelle version.
    La version active (is_active=True) est celle utilisée pour l'exécution.
    """
    __tablename__ = "playwright_script_versions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    test_case_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # 1, 2, 3... incrémenté à chaque nouvelle version
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Le script TypeScript complet
    script_content: Mapped[str] = mapped_column(Text, nullable=False)

    # True = version actuellement utilisée pour les runs
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

    # Résultat de "Valider syntaxe"
    validation_status: Mapped[ScriptValidationStatus] = mapped_column(
        SqlEnum(ScriptValidationStatus),
        default=ScriptValidationStatus.NOT_VALIDATED,
        nullable=False
    )

    # Message d'erreur si validation_status=invalid
    validation_error: Mapped[Optional[str]] = mapped_column(Text)

    # Origine du script — v1_draft (placeholders) ou v2_corrected (locators réels)
    source: Mapped[ScriptSource] = mapped_column(
        SqlEnum(ScriptSource),
        default=ScriptSource.V1_DRAFT,
        nullable=False
    )

    # Nombre de placeholders [TESTFORGEAI: ...] restants — 0 = script exécutable
    placeholder_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ==============================
    # RELATIONS
    # ==============================

    test_case: Mapped["TestCase"] = relationship(
        "TestCase",
        back_populates="script_versions",
        primaryjoin="PlaywrightScriptVersion.test_case_id == TestCase.id",
        foreign_keys="[PlaywrightScriptVersion.test_case_id]",
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_script_version_test_case_id", "test_case_id"),
        Index("idx_script_version_is_active", "test_case_id", "is_active"),
        Index("idx_script_version_number", "test_case_id", "version_number"),
    )
