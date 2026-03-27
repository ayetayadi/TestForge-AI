import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)   # ← False until setup
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # ← new
    setup_token: Mapped[str] = mapped_column(String(512), nullable=True)  # ← new
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    jira_connection: Mapped["JiraConnection"] = relationship(
        "JiraConnection",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )