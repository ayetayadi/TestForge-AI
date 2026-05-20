from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette import status

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import pwd_context
from app.models.user import User
from app.schemas.user_schema import UserRead, MessageResponse, ChangePasswordRequest, ProfileUpdate
from app.services.mail_service import send_password_changed_email

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserRead)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.jira_connection))
        .where(User.id == current_user.id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserRead(
        id=user.id,
        email=user.email,
        username=user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        created_at=user.created_at,
        jira_connected=user.jira_connection is not None
    )

@router.patch("/me", response_model=UserRead)
async def update_my_profile(
    payload: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing_email = await db.execute(
        select(User).where(User.email == payload.email, User.id != current_user.id)
    )
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already in use")

    existing_username = await db.execute(
        select(User).where(User.username == payload.username, User.id != current_user.id)
    )
    if existing_username.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already in use")

    current_user.email = payload.email
    current_user.username = payload.username
    await db.commit()
    await db.refresh(current_user)

    result = await db.execute(
        select(User).options(selectinload(User.jira_connection)).where(User.id == current_user.id)
    )
    user = result.scalar_one()
    return UserRead(
        id=user.id,
        email=user.email,
        username=user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        created_at=user.created_at,
        jira_connected=user.jira_connection is not None
    )


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    payload: ChangePasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not pwd_context.verify(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )

    current_user.hashed_password = pwd_context.hash(payload.new_password)

    await db.commit()
    await db.refresh(current_user)

    background_tasks.add_task(
        send_password_changed_email,
        current_user.email,
        current_user.username,
    )

    return MessageResponse(
        message="Password changed successfully. A confirmation email has been sent."
    )