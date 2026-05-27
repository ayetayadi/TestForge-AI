import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.utils.encryption_utils import encrypt, decrypt


class JiraConnection(Base):
    __tablename__ = "jira_connections"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    jira_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    jira_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    _access_token: Mapped[str] = mapped_column(
        "access_token",
        Text,
        nullable=False,
    )

    _refresh_token: Mapped[str | None] = mapped_column(
        "refresh_token",
        Text,
        nullable=True,
    )

    cloud_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    connected_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    user: Mapped["User"] = relationship(
        back_populates="jira_connection"
    )

    jira_projects: Mapped[list["JiraProject"]] = relationship(
        back_populates="jira_connection",
        cascade="all, delete-orphan",
    )

    @property
    def access_token(self) -> str:
        return decrypt(self._access_token)

    @access_token.setter
    def access_token(self, value: str) -> None:
        self._access_token = encrypt(value)

    @property
    def refresh_token(self) -> str | None:
        if not self._refresh_token:
            return None
        return decrypt(self._refresh_token)

    @refresh_token.setter
    def refresh_token(self, value: str | None) -> None:
        self._refresh_token = encrypt(value) if value else None