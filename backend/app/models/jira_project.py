import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class JiraProject(Base):
    __tablename__ = "jira_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    jira_connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("jira_connections.id"),
        nullable=False
    )

    project_key: Mapped[str] = mapped_column(String(50), nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # relations
    jira_connection: Mapped["JiraConnection"] = relationship(
        back_populates="jira_projects"
    )

    user_stories: Mapped[list["UserStory"]] = relationship(
        back_populates="jira_project",
        cascade="all, delete-orphan"
    )