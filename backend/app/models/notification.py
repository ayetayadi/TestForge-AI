import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, Index, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user_story import UserStory


class Notification(Base):
    """Alerte persistée quand une USER STORY est jugée trop ambiguë / incomplète.

    Simple trace d'un événement : "le système a signalé cette story".
    Rattachée UNIQUEMENT à la user story. Volontairement minimale —
    pas de sévérité ni de statut (ce n'est pas un bug à suivre, juste une alerte).
    """
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Quelle user story est concernée (le seul lien)
    user_story_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_stories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Le texte de l'alerte (ex: "Story trop ambiguë — score 18/100")
    message: Mapped[Optional[str]] = mapped_column(Text)

    # La liste des problèmes détectés (le POURQUOI)
    detected_issues: Mapped[List[str]] = mapped_column(
        JSONB, default=lambda: [], server_default="[]"
    )

    # Clé du ticket Jira si l'alerte a été envoyée (sinon NULL)
    jira_issue_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user_story: Mapped["UserStory"] = relationship(
        "UserStory",
        back_populates="notifications",
        foreign_keys=[user_story_id],
    )

    __table_args__ = (
        Index("idx_notification_user_story_id", "user_story_id"),
    )
