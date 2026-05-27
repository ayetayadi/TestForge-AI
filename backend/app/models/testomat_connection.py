import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.utils.encryption_utils import encrypt, decrypt


class TestomatConnection(Base):
    __tablename__ = "testomat_connections"

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

    _api_key: Mapped[str] = mapped_column(
        "api_key",
        Text,
        nullable=False,
    )

    connected_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship(back_populates="testomat_connection")

    @property
    def api_key(self) -> str:
        return decrypt(self._api_key)

    @api_key.setter
    def api_key(self, value: str) -> None:
        self._api_key = encrypt(value)

    @property
    def api_key_preview(self) -> str:
        """Return a masked preview like 'abc…xyz' for display."""
        raw = self.api_key
        if len(raw) <= 8:
            return "***"
        return raw[:4] + "…" + raw[-4:]
