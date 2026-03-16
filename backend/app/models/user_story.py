import uuid
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class UserStory(Base):
    __tablename__ = "user_stories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    jira_project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jira_projects.id"),
        nullable=False
    )

    issue_key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=True)

    # relation
    jira_project: Mapped["JiraProject"] = relationship(
        back_populates="user_stories"
    )