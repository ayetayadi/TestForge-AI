import uuid
import json
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user_story import UserStory


class Risk(Base):
    """
    Risk analysis for User Stories with Acceptance Criteria.
    
    LLM analyzes the story → gives P (1-5) and I (1-5) → Score = P × I
    
    Classification:
    - Critical: 20-25 → Comprehensive testing (60% effort)
    - High: 12-19     → Thorough testing (25% effort)
    - Medium: 6-11    → Standard testing (10% effort)
    - Low: 1-5        → Smoke tests (5% effort)
    """
    __tablename__ = "risks"

    # ==============================
    # PRIMARY KEY
    # ==============================
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # ==============================
    # FOREIGN KEY
    # ==============================
    user_story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_stories.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    test_plan_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )

    # ==============================
    # SOURCE TRACEABILITY
    # ==============================
    # What exact text was analyzed?
    source_story_text: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # The analyzed story (title + description)
    
    source_acceptance_criteria: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # JSON of ACs: ["AC1", "AC2", "AC3"]
    
    source: Mapped[str] = mapped_column(
        String(20), default="original", nullable=False
    )  # "original" | "approved_version"

    # ==============================
    # LLM RESULT: PROBABILITY (1-5)
    # ==============================
    probability: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 1-5: How likely is a bug to occur?
    
    probability_factors: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True
    )  # Detail: {"complexity": 4, "change_rate": 2, "dev_experience": 3, "tech_debt": 1}
    
    probability_reasoning: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Why this P? "Complex logic + new developer + many acceptance criteria"

    # ==============================
    # LLM RESULT: IMPACT (1-5)
    # ==============================
    impact: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 1-5: If a bug occurs, how bad is the impact?
    
    impact_factors: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True
    )  # Detail: {"users": 5, "revenue": 4, "safety": 2, "reputation": 3}
    
    impact_reasoning: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Why this I? "All users affected + direct revenue loss"

    # ==============================
    # CALCULATED SCORE
    # ==============================
    risk_score: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # P × I (1-25)
    
    level: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # critical | high | medium | low

    # ==============================
    # RISK DESCRIPTION
    # ==============================
    description: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # "Payment fails when applying promo code during peak hours"
    
    mitigation: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # "Test checkout with 10 promo codes + load test 1000 concurrent users"
    
    reasoning: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Full summary of LLM analysis (3 bullet points)

    # ==============================
    # RECOMMENDED TEST PLAN
    # ==============================
    test_depth: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # comprehensive | thorough | standard | smoke

    # ==============================
    # METADATA
    # ==============================
    is_ai_generated: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )
    
    is_accepted: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )  # Has the QA lead validated this analysis?
    
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # When was it accepted/rejected?

    # ==============================
    # TIMESTAMPS
    # ==============================
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(), 
        nullable=False
    )

    # ==============================
    # RELATIONSHIPS
    # ==============================
    user_story: Mapped[Optional["UserStory"]] = relationship(
        "UserStory", back_populates="risks"
    )

    # ==============================
    # COMPUTED PROPERTIES
    # ==============================
    @property
    def user_story_key(self) -> Optional[str]:
        """Get the Jira issue key of the associated User Story."""
        return self.user_story.issue_key if self.user_story else None

    @property
    def user_story_title(self) -> Optional[str]:
        """Get the title of the associated User Story."""
        return self.user_story.title if self.user_story else None

    @property
    def parsed_acceptance_criteria(self) -> List[str]:
        """Deserialize the stored JSON acceptance criteria."""
        if not self.source_acceptance_criteria:
            return []
        try:
            return json.loads(self.source_acceptance_criteria)
        except (json.JSONDecodeError, TypeError):
            return []

    @property
    def is_critical(self) -> bool:
        """Score ≥ 20 → Comprehensive testing required."""
        return self.risk_score >= 20

    @property
    def is_high_priority(self) -> bool:
        """Score ≥ 12 → Thorough testing required."""
        return self.risk_score >= 12

    @property
    def risk_matrix_position(self) -> str:
        """
        Return the position in the risk matrix.
        Example: "P4-I5" = Probability 4, Impact 5
        """
        return f"P{self.probability}-I{self.impact}"

    # ==============================
    # UTILITY METHODS
    # ==============================
    def accept(self) -> None:
        """QA lead accepts this risk analysis."""
        self.is_accepted = True
        self.accepted_at = datetime.utcnow()

    def reject(self) -> None:
        """QA lead rejects this risk analysis."""
        self.is_accepted = False
        self.accepted_at = datetime.utcnow()

    def get_summary(self) -> str:
        """
        Return a one-line summary of the risk assessment.
        Example: "[CRITICAL] Payment fails with promo code (P4×I5=20)"
        """
        return f"[{self.level.upper()}] {self.description} (P{self.probability}×I{self.impact}={self.risk_score})"

    # ==============================
    # REPRESENTATION
    # ==============================
    def __repr__(self) -> str:
        return (
            f"<Risk("
            f"story={self.user_story_key}, "
            f"P={self.probability}, "
            f"I={self.impact}, "
            f"Score={self.risk_score}, "
            f"Level={self.level}, "
            f"Tests={self.test_depth}"
            f")>"
        )

    # ==============================
    # INDEXES
    # ==============================
    __table_args__ = (
        Index("idx_risk_user_story_id", "user_story_id"),
        Index("idx_risk_level", "level"),
        Index("idx_risk_score", "risk_score"),
        Index("idx_risk_probability_impact", "probability", "impact"),
    )