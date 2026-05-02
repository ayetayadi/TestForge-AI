from datetime import datetime
import uuid
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text, Float, ForeignKey, Index, Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy import UniqueConstraint
from app.core.database import Base
from app.models.enums import StoryDecision, WorkflowStatus


class UserStoryVersion(Base):
    __tablename__ = "user_story_versions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    user_story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_stories.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Numéro de version incrémental par User Story (1, 2, 3...)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    improved_story: Mapped[str] = mapped_column(Text, nullable=False)

    generated_acceptance_criteria: Mapped[List[str]] = mapped_column(
        JSONB,
        default=lambda: [],
        server_default="[]"
    )

    # =========================
    # SCORES
    # =========================
    initial_score: Mapped[Optional[float]] = mapped_column(Float)
    final_score: Mapped[Optional[float]] = mapped_column(Float)

    # =========================
    # TESTABILITY
    # =========================
    testability_score: Mapped[Optional[float]] = mapped_column(Float)
    is_testable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    testability_issues: Mapped[Optional[List[str]]] = mapped_column(JSONB)

    # =========================
    # DECISION
    # =========================
    decision_status: Mapped[StoryDecision] = mapped_column(
        SqlEnum(StoryDecision),
        default=StoryDecision.PENDING,
        nullable=False
    )
  
    # =========================
    # USER CUSTOMIZATION
    # =========================
    is_customized: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false"
    )
    
    customized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
    )

    # =========================
    # META
    # =========================

    workflow_status: Mapped[WorkflowStatus] = mapped_column(
        SqlEnum(WorkflowStatus),
        default=WorkflowStatus.PROCESSING,
        nullable=False
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
        ) 
    

    # =========================
    # RELATIONS
    # =========================
    user_story = relationship(
        "UserStory",
        back_populates="versions",
        foreign_keys=[user_story_id]
    )

    defects = relationship(
        "Defect",
        back_populates="user_story_version",
        foreign_keys="Defect.user_story_version_id"
    )

    # =========================
    # INDEX OPTIMISÉS
    # =========================
    __table_args__ = (
        UniqueConstraint("user_story_id", "version_number", name="uq_user_story_version"),
        # Index simple sur user_story_id (déjà fait par index=True)
        # Mais on garde un index nommé pour les requêtes complexes
        Index("idx_version_user_story_id", "user_story_id"),
        
        # Pour filtrer par statut (dashboard, monitoring)
        Index("idx_version_workflow_status", "workflow_status"),
        
        # Pour trier par date (historique, timeline)
        Index("idx_version_started_at", "started_at"),
        
        # Pour chercher les versions complétées dans une plage de temps
        Index("idx_version_completed_at", "completed_at"),
        
        # Pour trouver rapidement la dernière version d'une story
        Index("idx_version_story_workflow_status_date", 
              "user_story_id", "workflow_status", "started_at"),
        
        # Pour les analyses de performance
        Index("idx_version_score", "final_score"),
        
        # Pour le workflow d'approbation
        Index("idx_version_decision", "decision_status", "workflow_status"),
    )