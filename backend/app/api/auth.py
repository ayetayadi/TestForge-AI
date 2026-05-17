import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.core.security import (
    verify_password,
    hash_password,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from app.models.user import User
from app.schemas.user_schema import (
    LoginRequest, TokenResponse, SetupPasswordRequest,
    ForgotPasswordRequest, ResetPasswordRequest,
)
from app.api.deps import get_current_user
from app.services.mail_service import send_reset_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

# ---------------------------------------------------------------------------
# Token blacklist — Redis-backed with automatic in-memory fallback
# ---------------------------------------------------------------------------
_mem_blacklist: set[str] = set()


async def _blacklist_jti(jti: str) -> None:
    """Revoke a token by JTI. Uses Redis when available, falls back to memory."""
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        if redis:
            ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
            await redis.setex(f"blacklist:{jti}", ttl, "1")
            return
    except Exception:
        pass
    _mem_blacklist.add(jti)


async def _is_blacklisted(jti: str) -> bool:
    """Return True if the JTI has been revoked."""
    try:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        if redis:
            return await redis.exists(f"blacklist:{jti}") == 1
    except Exception:
        pass
    return jti in _mem_blacklist


# ---------------------------------------------------------------------------
# Cookie helper — secure flag is OFF locally, ON in production
# ---------------------------------------------------------------------------
_SECURE_COOKIE = settings.ENV not in ("dev", "local", "development")
_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days in seconds


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=_SECURE_COOKIE,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
    )


# ---------------------------------------------------------------------------
# LOGIN
# ---------------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    token_data = {"sub": str(user.id), "is_admin": user.is_admin, "email": user.email}
    access_token = create_access_token(token_data)
    refresh_token, jti = create_refresh_token(token_data)

    _set_refresh_cookie(response, refresh_token)

    return TokenResponse(access_token=access_token, token_type="bearer")

# ---------------------------------------------------------------------------
# REFRESH
# ---------------------------------------------------------------------------
@router.post("/refresh")
async def refresh_access_token(
    response: Response,
    refresh_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db),
):
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token provided")

    payload = decode_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    jti = payload.get("jti")
    
    if jti and await _is_blacklisted(jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

    exp = payload.get("exp")
    if exp and datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    token_data = {"sub": str(user.id), "is_admin": user.is_admin, "email": user.email}
    new_access_token = create_access_token(token_data)
    new_refresh_token, new_jti = create_refresh_token(token_data)

    if jti:
        asyncio.create_task(_delayed_blacklist(jti, delay=5))

    _set_refresh_cookie(response, new_refresh_token)
    return {"access_token": new_access_token, "token_type": "bearer"}

async def _delayed_blacklist(jti: str, delay: int = 5):
    """Blacklist un JTI après un délai pour éviter les problèmes de requêtes simultanées"""
    await asyncio.sleep(delay)
    await _blacklist_jti(jti)
    
# ---------------------------------------------------------------------------
# LOGOUT
# ---------------------------------------------------------------------------
@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: Optional[str] = Cookie(None),
):
    if refresh_token:
        payload = decode_refresh_token(refresh_token)
        if payload and payload.get("jti"):
            await _blacklist_jti(payload["jti"])

    response.delete_cookie("refresh_token")
    return {"message": "Logged out successfully"}


@router.post("/logout-all")
async def logout_all_devices(
    response: Response,
    current_user: User = Depends(get_current_user),
    refresh_token: Optional[str] = Cookie(None),
):
    if refresh_token:
        payload = decode_refresh_token(refresh_token)
        if payload and payload.get("jti"):
            await _blacklist_jti(payload["jti"])

    response.delete_cookie("refresh_token")
    return {"message": "Logged out from all devices"}


# ---------------------------------------------------------------------------
# PASSWORD RESET
# ---------------------------------------------------------------------------
@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Always return 200 — never reveal whether the email exists
    if not user or not user.is_active:
        return {"message": "If that email is registered, a reset link has been sent."}

    token = secrets.token_urlsafe(48)
    user.reset_token = token
    user.reset_token_expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).replace(tzinfo=None)
    await db.commit()

    try:
        await send_reset_email(user.email, user.username, token)
    except Exception:
        user.reset_token = None
        user.reset_token_expires_at = None
        await db.commit()
        raise HTTPException(status_code=500, detail="Failed to send email. Please try again.")

    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    result = await db.execute(select(User).where(User.reset_token == payload.token))
    user = result.scalar_one_or_none()

    if not user or not user.reset_token_expires_at:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    if datetime.utcnow() > user.reset_token_expires_at:
        user.reset_token = None
        user.reset_token_expires_at = None
        await db.commit()
        raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")

    user.hashed_password = hash_password(payload.new_password)
    user.reset_token = None
    user.reset_token_expires_at = None
    await db.commit()
    return {"message": "Password reset successfully. You can now log in."}


@router.post("/setup-password")
async def setup_password(
    payload: SetupPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.setup_token == payload.token))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired setup link")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user.hashed_password = hash_password(payload.password)
    user.is_active = True
    user.is_verified = True
    user.setup_token = None
    await db.commit()
    return {"message": "Password set successfully. You can now log in."}
