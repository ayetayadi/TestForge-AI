import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, ForeignKey, Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base
from app.models.enums import OutcomeEnum, HumanChoiceEnum, SourceEnum, StatusEnum


class UserStoryFinal(Base):
    __tablename__ = "user_stories_final"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    user_story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_stories.id"),
        unique=True,
        nullable=False
    )

    # ── CONTENU ─────────────────────────────
    issue_key = Column(String, index=True) 
    
    raw_story: Mapped[str] = mapped_column(Text, nullable=False)

    improved_story: Mapped[str] = mapped_column(Text, nullable=True)

    acceptance_criteria: Mapped[list] = mapped_column(JSONB, nullable=True)

    # ── SCORES ──────────────────────────────
    score_before: Mapped[float] = mapped_column(Float, nullable=True)
    score_after: Mapped[float] = mapped_column(Float, nullable=True)
    delta: Mapped[float] = mapped_column(Float, nullable=True)

    # ── PIPELINE ────────────────────────────
    iteration: Mapped[int] = mapped_column(Integer, default=0)

    outcome: Mapped[str] = mapped_column(
        OutcomeEnum,
        nullable=False
    )

    human_choice: Mapped[str] = mapped_column(
        HumanChoiceEnum,
        nullable=True
    )

    source: Mapped[str] = mapped_column(
        SourceEnum,
        default="ai"
    )

    # ── STATUT ──────────────────────────────
    status: Mapped[str] = mapped_column(
        StatusEnum,
        default="completed",
        nullable=False
    )

    current_step: Mapped[str] = mapped_column(String(50), nullable=True)

    events: Mapped[list] = mapped_column(JSONB, default=list)

    # ── SSE / ASYNC ─────────────────────────
    job_id: Mapped[str] = mapped_column(String(36), nullable=True)

    alert_message: Mapped[str] = mapped_column(Text, nullable=True)

    

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # ── RELATION ────────────────────────────
    user_story: Mapped["UserStory"] = relationship(
        "UserStory",
        back_populates="final_version"
    )