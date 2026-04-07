from datetime import datetime
import uuid
from sqlalchemy import DateTime, String, Text, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base


class UserStory(Base):
    __tablename__ = "user_stories"

    id: Mapped[str] = mapped_column(
        String(36), 
        primary_key=True, 
        default=lambda: str(uuid.uuid4())
    )

    jira_project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jira_projects.id"),
        nullable=False
    )

    issue_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # ── Contenu principal ──
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[list] = mapped_column(JSONB, nullable=True)

    # ── Métadonnées Jira ──
    issue_type: Mapped[str] = mapped_column(String(50), nullable=True)
    priority: Mapped[str] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=True)
    story_points: Mapped[float] = mapped_column(Float, nullable=True)

    # ── Personnes ──
    assignee: Mapped[str] = mapped_column(String(200), nullable=True)
    reporter: Mapped[str] = mapped_column(String(200), nullable=True)

    # ── Organisation Agile ──
    epic_key: Mapped[str] = mapped_column(String(100), nullable=True)
    epic_name: Mapped[str] = mapped_column(String(300), nullable=True)
    sprint: Mapped[str] = mapped_column(String(200), nullable=True)
    labels: Mapped[list] = mapped_column(JSONB, nullable=True)
    components: Mapped[list] = mapped_column(JSONB, nullable=True)

    # ── Versioning ──
    fix_version: Mapped[str] = mapped_column(String(100), nullable=True)

    # ── Pipeline ──
    job_id: Mapped[str] = mapped_column(String(36), nullable=True)

    # ── Timestamps ──
    jira_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    jira_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )

    # ── Relations (strings pour éviter l'import circulaire) ──
    jira_project: Mapped["JiraProject"] = relationship(
        "JiraProject",
        back_populates="user_stories"
    )

    final_version: Mapped["UserStoryFinal"] = relationship(
        "UserStoryFinal",
        back_populates="user_story",
        uselist=False,
        cascade="all, delete-orphan"
    )