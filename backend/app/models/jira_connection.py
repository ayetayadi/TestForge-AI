import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.utils.security.encryption import encrypt, decrypt


class JiraConnection(Base):
    __tablename__ = "jira_connections"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=False
    )

    jira_url: Mapped[str] = mapped_column(String(500), nullable=False)
    jira_email: Mapped[str] = mapped_column(String(255), nullable=False)

    _jira_api_token: Mapped[str] = mapped_column(
        "jira_api_token",
        Text,
        nullable=False
    )

    cloud_id: Mapped[str] = mapped_column(String(100), nullable=True)

    connected_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True
    )

    user: Mapped["User"] = relationship(
        back_populates="jira_connection"
    )

    jira_projects: Mapped[list["JiraProject"]] = relationship(
        back_populates="jira_connection",
        cascade="all, delete-orphan"
    )

    @property
    def jira_api_token(self) -> str:
        return decrypt(self._jira_api_token)

    @jira_api_token.setter
    def jira_api_token(self, value: str):
        self._jira_api_token = encrypt(value)