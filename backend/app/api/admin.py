from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.security import hash_password
from app.models.user import User
from app.models.jira_connection import JiraConnection
from app.models.jira_project import JiraProject
from app.models.user_story import UserStory
from app.models.test_plan import TestPlan
from app.models.test_case import TestCase
from app.models.risk import Risk
from app.schemas.user_schema import UserCreate, UserRead, UserUpdate
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
        hashed_password=hash_password(secrets.token_urlsafe(16)),  # temp random password
        is_admin=payload.is_admin,
        is_active=False,           # inactive until they set password
        is_verified=False,
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

@router.put("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check email uniqueness
    existing_email = await db.execute(
        select(User).where(User.email == payload.email, User.id != user_id)
    )
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Check username uniqueness
    existing_username = await db.execute(
        select(User).where(User.username == payload.username, User.id != user_id)
    )
    if existing_username.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    user.email = payload.email
    user.username = payload.username
    user.is_admin = payload.is_admin
    user.is_active = payload.is_active

    await db.commit()

    result = await db.execute(
        select(User)
        .options(selectinload(User.jira_connection))
        .where(User.id == user.id)
    )
    user = result.scalar_one()

    return _to_read(user)

def is_jira_connected(user: User) -> bool:
    if user.is_admin:
        return False
    jira_conn = user.jira_connection
    if not jira_conn:
        return False
    return bool(jira_conn.is_active)

def _to_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        username=user.username,
        is_admin=user.is_admin,
        is_active=user.is_active,
        created_at=user.created_at,
        jira_connected=is_jira_connected(user),
    )


@router.get("/analytics")
async def get_admin_analytics(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    # Load all non-admin users with their Jira connections and projects
    users_result = await db.execute(
        select(User)
        .options(
            selectinload(User.jira_connection).selectinload(JiraConnection.jira_projects)
        )
        .where(User.is_admin == False)
    )
    testers = users_result.scalars().all()

    # Global platform counts
    g_projects   = (await db.execute(select(func.count()).select_from(JiraProject))).scalar() or 0
    g_stories    = (await db.execute(select(func.count()).select_from(UserStory))).scalar() or 0
    g_tc         = (await db.execute(select(func.count()).select_from(TestCase))).scalar() or 0
    g_tp         = (await db.execute(select(func.count()).select_from(TestPlan))).scalar() or 0
    g_risks      = (await db.execute(select(func.count()).select_from(Risk))).scalar() or 0

    testers_data = []
    for user in testers:
        projects_data = []
        t_stories = t_tc = t_tp = t_risks = 0

        if user.jira_connection:
            for proj in user.jira_connection.jira_projects:
                pid = proj.id

                s_count = (await db.execute(
                    select(func.count()).select_from(UserStory)
                    .where(UserStory.project_id == pid)
                )).scalar() or 0

                sid_rows = (await db.execute(
                    select(UserStory.id).where(UserStory.project_id == pid)
                )).scalars().all()

                tc_count = risk_count = 0
                if sid_rows:
                    tc_count = (await db.execute(
                        select(func.count()).select_from(TestCase)
                        .where(TestCase.user_story_id.in_(sid_rows))
                    )).scalar() or 0
                    risk_count = (await db.execute(
                        select(func.count()).select_from(Risk)
                        .where(Risk.user_story_id.in_(sid_rows))
                    )).scalar() or 0

                tp_count = (await db.execute(
                    select(func.count()).select_from(TestPlan)
                    .where(TestPlan.project_id == pid)
                )).scalar() or 0

                t_stories  += s_count
                t_tc       += tc_count
                t_tp       += tp_count
                t_risks    += risk_count

                projects_data.append({
                    "id": pid,
                    "project_key": proj.project_key,
                    "project_name": proj.project_name,
                    "story_count": s_count,
                    "test_case_count": tc_count,
                    "test_plan_count": tp_count,
                    "risk_count": risk_count,
                })

        testers_data.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "jira_connected": is_jira_connected(user),
            "project_count": len(projects_data),
            "total_stories": t_stories,
            "total_test_cases": t_tc,
            "total_test_plans": t_tp,
            "total_risks": t_risks,
            "projects": projects_data,
        })

    return {
        "global": {
            "total_testers": len(testers),
            "total_projects": g_projects,
            "total_stories": g_stories,
            "total_test_cases": g_tc,
            "total_test_plans": g_tp,
            "total_risks": g_risks,
        },
        "testers": testers_data,
    }