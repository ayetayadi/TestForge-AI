import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.playwright_script_version import PlaywrightScriptVersion
    from app.models.test_suite import TestSuite
    from app.models.test_case_dependency import TestCaseDependency
    from app.models.defect import Defect
    from app.models.user_story import UserStory
    from app.models.test_plan import TestPlan


class TestCase(Base):

    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # TC-001, TC-002... généré à la création
    tc_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False)

    user_story_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("user_stories.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Suite parente (SET NULL — supprimer la suite ne supprime pas les cas de test)
    test_suite_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("test_suites.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    test_plan_id: Mapped[str] = mapped_column(
            String(36),
            ForeignKey("test_plans.id", ondelete="CASCADE"),
            nullable=False,
            index=True
        )
    
    # ==============================
    # CONTENU DU TEST
    # ==============================

    description: Mapped[Optional[str]] = mapped_column(Text)

    # Type du scénario : positive | negative | edge_case
    test_type: Mapped[Optional[str]] = mapped_column(String(20))

    # Niveau de risque métier : critical | high | medium | low (hérité du risque de la User Story)
    risk_level: Mapped[Optional[str]] = mapped_column(String(20))

    # Conditions requises avant l'exécution
    preconditions: Mapped[List[str]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]"
    )

    # Conditions vérifiées après l'exécution
    postconditions: Mapped[List[str]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]"
    )

    # Étapes structurées
    # [{"order": 1, "action": "Naviguer vers /login", "expected": "Page login affichée"}]
    steps: Mapped[List[dict]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]"
    )

    # Scénario Given/When/Then complet
    gherkin_source: Mapped[Optional[str]] = mapped_column(Text)

    # {"email": "test@example.com", "password": "SecurePass123!"}
    test_data: Mapped[Optional[dict]] = mapped_column(JSONB)

    expected_results: Mapped[List[str]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]"
    )

    # Locators Playwright pour l'exécution automatisée
    # [{"name": "emailInput", "selector": "[data-testid='email-input']", "reliability": "high"}]
    locators: Mapped[Optional[List[dict]]] = mapped_column(JSONB)

    # Référence directe au script Playwright actif (V2_CORRECTED le plus récent)
    active_playwright_script_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("playwright_script_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Ordre d'exécution dans le plan priorisé (calculé par l'algorithme §p.245)
    execution_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Exclut ce TC de l'exécution de la suite sans le supprimer (ISTQB §5.3 — skip)
    excluded_from_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Durée estimée d'exécution en minutes (estimée par le LLM à la génération)
    estimated_duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Cross-cutting suite candidacy flags (set during suite generation)
    is_smoke_candidate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="Critical/high positive TC in a core flow — qualifies for Smoke suite"
    )
    is_risk_based_candidate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
        comment="Critical/high risk TC — qualifies for Risk-Based suite"
    )

    _covered_ac_indices: Mapped[Optional[List[int]]] = mapped_column(
        JSONB, nullable=True, default=lambda: []
    )
    
    _reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # ==============================
    # META
    # ==============================

    @property
    def covered_ac_indices(self) -> List[int]:
        return self._covered_ac_indices or []

    @property
    def ac_coverage_reasoning(self) -> Optional[str]:
        return self._reasoning

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ==============================
    # RELATIONS
    # ==============================
    user_story: Mapped[Optional["UserStory"]] = relationship("UserStory", foreign_keys=[user_story_id], overlaps="test_cases")

    test_suite: Mapped[Optional["TestSuite"]] = relationship(
        "TestSuite",
        back_populates="test_cases",
        foreign_keys=[test_suite_id]
    )


    test_plan: Mapped["TestPlan"] = relationship("TestPlan", back_populates="test_cases")

    script_versions: Mapped[List["PlaywrightScriptVersion"]] = relationship(
        "PlaywrightScriptVersion",
        back_populates="test_case",
        cascade="all, delete-orphan",
        primaryjoin="TestCase.id == PlaywrightScriptVersion.test_case_id",
        foreign_keys="[PlaywrightScriptVersion.test_case_id]",
        order_by="PlaywrightScriptVersion.version_number"
    )

    active_playwright_script: Mapped[Optional["PlaywrightScriptVersion"]] = relationship(
        "PlaywrightScriptVersion",
        primaryjoin="TestCase.active_playwright_script_id == PlaywrightScriptVersion.id",
        foreign_keys="[TestCase.active_playwright_script_id]",
        uselist=False,
        viewonly=True,
    )

    # Dépendances où CE test est la source (il doit s'exécuter avant d'autres)
    source_dependencies: Mapped[List["TestCaseDependency"]] = relationship(
        "TestCaseDependency",
        back_populates="source_test_case",
        foreign_keys="TestCaseDependency.source_test_case_id",
        cascade="all, delete-orphan"
    )

    # Dépendances où CE test est la cible (d'autres doivent s'exécuter avant lui)
    target_dependencies: Mapped[List["TestCaseDependency"]] = relationship(
        "TestCaseDependency",
        back_populates="target_test_case",
        foreign_keys="TestCaseDependency.target_test_case_id",
        cascade="all, delete-orphan"
    )

    # Défauts trouvés lors de l'exécution de ce test
    defects: Mapped[List["Defect"]] = relationship(
        "Defect",
        back_populates="test_case",
        foreign_keys="Defect.test_case_id"
    )
    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_test_case_tc_code", "tc_code"),
        Index("idx_test_case_user_story_id", "user_story_id"),
        Index("idx_test_case_test_suite_id", "test_suite_id"),
        Index("idx_test_case_test_plan_id", "test_plan_id"),
        Index("idx_test_case_test_type", "test_type"),
        Index("idx_test_case_is_active", "is_active"),
        Index("idx_test_case_execution_order", "execution_order"),
    )
