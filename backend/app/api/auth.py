from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import verify_password, hash_password, create_access_token
from app.models.user import User
from app.schemas.user_schema import LoginRequest, TokenResponse, SetupPasswordRequest, UserRead , ForgotPasswordRequest, ResetPasswordRequest
from app.api.deps import get_current_user
import secrets
from datetime import datetime, timedelta
from app.schemas.user_schema import ForgotPasswordRequest, ResetPasswordRequest
from app.services.mail_service import send_reset_email

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled"
        )

    token = create_access_token({"sub": str(user.id), "is_admin": user.is_admin})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
    )


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Always return 200 — never reveal whether email exists
    if not user or not user.is_active:
        return {"message": "If that email is registered, a reset link has been sent."}

    token = secrets.token_urlsafe(48)
    user.reset_token            = token
    user.reset_token_expires_at = datetime.utcnow() + timedelta(minutes=30)
    await db.commit()

    try:
        await send_reset_email(user.email, user.username, token)
    except Exception as e:
        # Roll back token if email fails so user can retry
        user.reset_token            = None
        user.reset_token_expires_at = None
        await db.commit()
        raise HTTPException(status_code=500,
                            detail="Failed to send email. Please try again.")

    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    result = await db.execute(
        select(User).where(User.reset_token == payload.token)
    )
    user = result.scalar_one_or_none()

    if not user or not user.reset_token_expires_at:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    if datetime.utcnow() > user.reset_token_expires_at:
        # Clean up expired token
        user.reset_token            = None
        user.reset_token_expires_at = None
        await db.commit()
        raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")

    user.hashed_password        = hash_password(payload.new_password)
    user.reset_token            = None
    user.reset_token_expires_at = None
    await db.commit()

    return {"message": "Password reset successfully. You can now log in."}

@router.post("/setup-password")
async def setup_password(
    payload: SetupPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    # Find user by token
    result = await db.execute(
        select(User).where(User.setup_token == payload.token)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired setup link")

    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user.hashed_password = hash_password(payload.password)
    user.is_active = True           # activate account
    user.is_verified = True
    user.setup_token = None         # invalidate token after use
    await db.commit()

    return {"message": "Password set successfully. You can now log in."}

