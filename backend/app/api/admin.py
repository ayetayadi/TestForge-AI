from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user_schema import UserCreate, UserRead
from app.api.deps import get_current_admin
from app.services.mail_service import send_account_setup_email
import uuid
import secrets

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(
    payload: UserCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    setup_token = secrets.token_urlsafe(32)  # secure random token

    user = User(
        id=str(uuid.uuid4()),
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(secrets.token_urlsafe(16)),
        is_admin=payload.is_admin,
        is_active=False,
        is_verified=False,
        must_change_password=True,
        setup_token=setup_token,
    )
    db.add(user)
    await db.commit()

    # Reload with relationship
    result = await db.execute(
        select(User)
        .options(selectinload(User.jira_connection))
        .where(User.id == user.id)
    )
    user = result.scalar_one()

    # Send email in background (non-blocking)
    background_tasks.add_task(
        send_account_setup_email,
        email=payload.email,
        username=payload.username,
        setup_token=setup_token,
    )

    return _to_read(user)


@router.get("/users", response_model=list[UserRead])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    result = await db.execute(
        select(User).options(selectinload(User.jira_connection))
    )
    users = result.scalars().all()
    return [_to_read(u) for u in users]


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()


def _to_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        username=user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
        jira_connected=user.jira_connection is not None,
    )