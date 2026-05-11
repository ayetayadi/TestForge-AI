# app/core/security.py
from datetime import datetime, timedelta, timezone
from typing import Tuple
import uuid
from jose import jwt, JWTError
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _utcnow() -> datetime:
    """Single source of truth for current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    now = _utcnow()
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access", "iat": now})
    return jwt.encode(to_encode, settings.ACCESS_TOKEN_SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> Tuple[str, str]:
    """Returns (token, jti) where jti is the unique identifier used for blacklisting."""
    to_encode = data.copy()
    jti = str(uuid.uuid4())
    now = _utcnow()
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh", "jti": jti, "iat": now})
    token = jwt.encode(to_encode, settings.REFRESH_TOKEN_SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.ACCESS_TOKEN_SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload if payload.get("type") == "access" else None
    except JWTError:
        return None


def decode_refresh_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.REFRESH_TOKEN_SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload if payload.get("type") == "refresh" else None
    except JWTError:
        return None


def get_token_expires_in_seconds(token: str, is_refresh: bool = False) -> int:
    """Returns seconds until token expiry, or 0 if expired/invalid."""
    try:
        payload = decode_refresh_token(token) if is_refresh else decode_access_token(token)
        if payload and "exp" in payload:
            return max(0, int(payload["exp"] - _utcnow().timestamp()))
    except Exception:
        pass
    return 0
