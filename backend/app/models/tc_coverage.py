import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Float, Integer, String, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class TcCoverage(Base):
    """AC coverage record per (test_plan, user_story, scenario_type).

    One row is upserted each time TCs of a given type are generated for a US.
    Unique constraint on (test_plan_id, user_story_id, scenario_type) so
    re-generating the same type replaces the previous coverage record.
    """

    __tablename__ = "tc_coverages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    test_plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("test_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_stories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Denormalized for fast display without join
    issue_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    user_story_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # positive | negative | boundary
    scenario_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # AC coverage metrics
    coverage_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    covered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_ac_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Number of TCs generated in this run
    tc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("test_plan_id", "user_story_id", "scenario_type", name="uq_tc_coverage"),
        Index("idx_tc_coverage_plan", "test_plan_id"),
        Index("idx_tc_coverage_us", "user_story_id"),
    )
