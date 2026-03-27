from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import verify_password, hash_password, create_access_token
from app.models.user import User
from app.schemas.user_schema import LoginRequest, TokenResponse, ChangePasswordRequest, SetupPasswordRequest, UserRead
from app.api.deps import get_current_user

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


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False      # ← mark as done
    await db.commit()
    return {"message": "Password changed successfully"}

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

