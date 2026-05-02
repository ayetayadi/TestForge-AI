import uuid
from sqlalchemy import String, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class JiraProject(Base):
    __tablename__ = "jira_projects"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    jira_connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jira_connections.id", ondelete="CASCADE"),
        nullable=False
    )

    project_key: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    project_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "jira_connection_id",
            "project_key",
            name="uq_project_per_connection"
        ),
        Index("idx_project_key", "project_key"),
    )

    jira_connection: Mapped["JiraConnection"] = relationship(
        "JiraConnection",
        back_populates="jira_projects"
    )

    user_stories: Mapped[list["UserStory"]] = relationship(
        "UserStory",
        back_populates="jira_project",
        cascade="all, delete-orphan"
    )

    test_plans: Mapped[list["TestPlan"]] = relationship(
        "TestPlan",
        back_populates="jira_project",
        cascade="all, delete-orphan"
    )

