import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class JiraConnection(Base):
    __tablename__ = "jira_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), unique=True, nullable=False)
    jira_url: Mapped[str] = mapped_column(String(500), nullable=False)
    jira_email: Mapped[str] = mapped_column(String(255), nullable=False)
    jira_api_token: Mapped[str] = mapped_column(Text, nullable=False)   # stores OAuth access_token
    refresh_token: Mapped[str] = mapped_column(Text, nullable=True)     # ✅ new: OAuth refresh token
    cloud_id: Mapped[str] = mapped_column(String(100), nullable=True)   # ✅ new: Atlassian cloud ID
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship(back_populates="jira_connection")

    jira_projects: Mapped[list["JiraProject"]] = relationship(
    back_populates="jira_connection",
    cascade="all, delete-orphan")
