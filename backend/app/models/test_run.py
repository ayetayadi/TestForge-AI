import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Float, Integer, String, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.enums import TestRunStatus

if TYPE_CHECKING:
    from app.models.playwright_script_version import PlaywrightScriptVersion
    from app.models.test_result import TestResult
    from app.models.test_step_result import TestStepResult


class TestRun(Base):
    """
    Une session d'exécution d'un TestCase.
    Contient la configuration (browser, URL, timeout...) et le statut global.
    """
    __tablename__ = "test_runs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Quelle version du script a été utilisée pour ce run
    # TestCase est accessible via : run.script_version.test_case
    script_version_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("playwright_script_versions.id", ondelete="CASCADE"),
        nullable=True
    )

    # ==============================
    # CONFIGURATION D'EXÉCUTION
    # ==============================

    base_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # chromium | firefox | webkit
    browser: Mapped[str] = mapped_column(
        String(50), default="chromium", nullable=False, server_default="chromium"
    )

    # "1920x1080" | "375x812" (mobile)
    viewport: Mapped[str] = mapped_column(
        String(20), default="1920x1080", nullable=False, server_default="1920x1080"
    )

    timeout_ms: Mapped[int] = mapped_column(
        Integer, default=30000, nullable=False, server_default="30000"
    )

    headless: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

    record_video: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    capture_screenshots_on_failure: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

    # ==============================
    # STATUT & RÉSULTAT
    # ==============================

    status: Mapped[TestRunStatus] = mapped_column(
        SqlEnum(TestRunStatus),
        default=TestRunStatus.RUNNING,
        nullable=False
    )

    duration: Mapped[Optional[float]] = mapped_column(Float)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ==============================
    # RELATIONS
    # ==============================

    script_version: Mapped[Optional["PlaywrightScriptVersion"]] = relationship(
        "PlaywrightScriptVersion", back_populates="test_runs"
    )

    result: Mapped[Optional["TestResult"]] = relationship(
        "TestResult", back_populates="test_run", uselist=False, cascade="all, delete-orphan"
    )

    steps: Mapped[List["TestStepResult"]] = relationship(
        "TestStepResult",
        back_populates="test_run",
        cascade="all, delete-orphan",
        order_by="TestStepResult.step_order"
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_test_run_status", "status"),
        Index("idx_test_run_started_at", "started_at"),
        Index("idx_test_run_script_version_id", "script_version_id"),
    )
