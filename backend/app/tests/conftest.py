"""
Pytest fixtures for TestForge-AI backend tests.

Uses SQLite in-memory for speed; PostgreSQL-specific features (JSONB, ondelete)
are tested via integration markers that require a real DB connection.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    User, JiraConnection, JiraProject, UserStory, UserStoryVersion,
    TestPlan, TestSuite, TestCase, Risk, Defect, TcCoverage,
    PlaywrightScriptVersion, TestExecution, TestCaseResult,
)
from app.core.database import Base

# ─── In-memory async SQLite engine ───────────────────────────────────────────
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
AsyncTestSession = async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="function")
async def db() -> AsyncSession:
    """Fresh DB per test: creates all tables, yields session, drops all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncTestSession() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ─── Factory helpers ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def user(db: AsyncSession) -> User:
    u = User(
        id="user-1",
        email="test@testforge.ai",
        username="testuser",
        hashed_password="hashed",
        is_active=True,
        is_admin=False,
        is_verified=True,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture
async def jira_project(db: AsyncSession, user: User) -> JiraProject:
    conn = JiraConnection(
        id="jconn-1",
        user_id=user.id,
        _access_token="encrypted_token",
        is_active=True,
    )
    db.add(conn)
    await db.flush()

    proj = JiraProject(
        id="proj-1",
        jira_connection_id=conn.id,
        project_key="TF",
        project_name="TestForge",
    )
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


@pytest_asyncio.fixture
async def user_story(db: AsyncSession, jira_project: JiraProject) -> UserStory:
    story = UserStory(
        id="us-1",
        project_id=jira_project.id,
        issue_key="TF-1",
        title="As a user I can log in",
        acceptance_criteria=["AC1: Email field visible", "AC2: Password field visible"],
    )
    db.add(story)
    await db.commit()
    await db.refresh(story)
    return story


@pytest_asyncio.fixture
async def test_plan(db: AsyncSession, jira_project: JiraProject) -> TestPlan:
    plan = TestPlan(
        id="plan-1",
        project_id=jira_project.id,
        title="Sprint 1 Test Plan",
        status="draft",
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@pytest_asyncio.fixture
async def test_case(db: AsyncSession, test_plan: TestPlan, user_story: UserStory) -> TestCase:
    tc = TestCase(
        id="tc-1",
        tc_code="TC-001",
        title="Verify login with valid credentials",
        test_plan_id=test_plan.id,
        user_story_id=user_story.id,
        test_type="positive",
        priority="high",
        steps=[{"order": 1, "action": "Navigate to /login", "expected": "Login page visible"}],
    )
    db.add(tc)
    await db.commit()
    await db.refresh(tc)
    return tc
