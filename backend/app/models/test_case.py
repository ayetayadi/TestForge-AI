import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import Boolean, DateTime, String, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.playwright_script_version import PlaywrightScriptVersion


class TestCase(Base):

    __tablename__ = "test_cases"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # TC-001, TC-002... généré à la création
    tc_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # Cas 2 & 3 : lien vers la UserStory source (null si test statique pur)
    user_story_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("user_stories.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Cas 3 uniquement : version raffinée approuvée (null si pas de pipeline refinement)
    user_story_version_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("user_story_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # ==============================
    # CONTENU DU TEST
    # ==============================

    # Description libre du test case
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Priorité explicite : critical | high | medium | low
    priority: Mapped[Optional[str]] = mapped_column(String(20))

    # ["positive", "smoke", "regression"]
    tags: Mapped[List[str]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]"
    )

    # Conditions requises avant l'exécution
    # ["L'utilisateur dispose d'un compte actif", "Le serveur est disponible"]
    preconditions: Mapped[List[str]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]"
    )

    # Conditions vérifiées après l'exécution
    # ["La session est fermée", "Les logs sont nettoyés"]
    postconditions: Mapped[List[str]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]"
    )

    # Étapes structurées du test
    # [{"order": 1, "action": "Naviguer vers /login", "expected": "Page login affichée"}]
    steps: Mapped[List[dict]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]"
    )

    # Scénario Given/When/Then complet
    gherkin_source: Mapped[Optional[str]] = mapped_column(Text)

    # {"email": "test@example.com", "password": "SecurePass123!"}
    test_data: Mapped[Optional[dict]] = mapped_column(JSONB)

    # ["URL est /dashboard", "Message de bienvenue affiché", "Token JWT stocké"]
    expected_results: Mapped[List[str]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]"
    )

    # ==============================
    # LOCATORS (JSONB pour MVP)
    # [{"name": "emailInput", "selector": "[data-testid='email-input']", "reliability": "high"}]
    # Future: table dédiée pour self-healing
    # ==============================
    locators: Mapped[Optional[List[dict]]] = mapped_column(JSONB)

    # ==============================
    # META
    # ==============================

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

    user_story = relationship("UserStory", foreign_keys=[user_story_id])
    user_story_version = relationship("UserStoryVersion", foreign_keys=[user_story_version_id])

    script_versions: Mapped[List["PlaywrightScriptVersion"]] = relationship(
        "PlaywrightScriptVersion",
        back_populates="test_case",
        cascade="all, delete-orphan",
        order_by="PlaywrightScriptVersion.version_number"
    )

    # ==============================
    # INDEX
    # ==============================

    __table_args__ = (
        Index("idx_test_case_tc_code", "tc_code"),
        Index("idx_test_case_user_story_id", "user_story_id"),
        Index("idx_test_case_user_story_version_id", "user_story_version_id"),
        Index("idx_test_case_is_active", "is_active"),
    )
