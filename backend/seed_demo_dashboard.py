"""
Seed script — enrich the tester dashboard with realistic demo data.

Usage (from the backend/ directory):
    python seed_demo_dashboard.py
    python seed_demo_dashboard.py --email your@email.com

The script is idempotent: projects are skipped if their project_key already
exists for the user.  Run it as many times as you like.
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

# ── bootstrap Django-style env before anything imports app code ────────────
import os, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from app.core.database import async_session_maker
from app.models.enums import TestExecutionStatus, TestPlanStatus, TestSuiteStatus
from app.models.jira_connection import JiraConnection
from app.models.jira_project import JiraProject
from app.models.risk import Risk
from app.models.test_case import TestCase
from app.models.test_execution import TestExecution
from app.models.test_plan import TestPlan
from app.models.test_suite import TestSuite
from app.models.user import User
from app.models.user_story import UserStory


# ═══════════════════════════════════════════════════════════════════════════
# Demo dataset
# Each entry:  (project_key, project_name, us_count, refined_count,
#               risk_count, suite_defs, exec_defs)
#   suite_defs  = list of (suite_title, tc_count)
#   exec_defs   = list of (passed, failed)
# ═══════════════════════════════════════════════════════════════════════════
PROJECTS = [
    (
        "ECOM", "E-Commerce Platform",
        18, 12, 14,
        [
            ("Authentication & Account", 5),
            ("Product Catalog & Search", 4),
            ("Shopping Cart & Checkout", 5),
            ("Payment Gateway", 4),
            ("Order Management", 4),
        ],
        [(18, 4), (20, 2), (14, 6), (22, 0)],
    ),
    (
        "MBANK", "Mobile Banking App",
        14, 9, 11,
        [
            ("Login & Biometrics", 4),
            ("Account Overview", 4),
            ("Transfers & Payments", 5),
            ("Notifications & Alerts", 3),
        ],
        [(12, 3), (14, 2), (10, 5)],
    ),
    (
        "HRPRT", "HR Self-Service Portal",
        10, 6, 7,
        [
            ("Employee Profile", 4),
            ("Leave Management", 4),
            ("Payslip & Documents", 3),
        ],
        [(9, 2), (10, 1)],
    ),
    (
        "INVY", "Inventory Management System",
        8, 4, 5,
        [
            ("Stock Tracking", 4),
            ("Supplier & Orders", 4),
        ],
        [(7, 1), (6, 2)],
    ),
    (
        "CSUP", "Customer Support Hub",
        6, 2, 3,
        [
            ("Ticket Submission", 3),
            ("Agent Dashboard", 2),
        ],
        [(3, 2)],
    ),
]


# ── Global TC code counter (unique across the whole run) ──────────────────
_tc_counter = 0


def _tc_code() -> str:
    global _tc_counter
    _tc_counter += 1
    return f"DMO-{_tc_counter:04d}"


def _uid() -> str:
    return str(uuid.uuid4())


def _ago(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


# ═══════════════════════════════════════════════════════════════════════════
async def seed(user_email: str) -> None:
    async with async_session_maker() as db:

        # ── 1. Resolve user ────────────────────────────────────────────────
        res = await db.execute(select(User).where(User.email == user_email))
        user: User | None = res.scalar_one_or_none()
        if user is None:
            print(f"[ERROR] No user found with email '{user_email}'.")
            print("        Pass the correct email: python seed_demo_dashboard.py --email X")
            return
        print(f"[OK] Found user: {user.username} ({user.email})")

        # ── 2. Ensure Jira connection ──────────────────────────────────────
        res = await db.execute(
            select(JiraConnection).where(JiraConnection.user_id == user.id)
        )
        conn: JiraConnection | None = res.scalar_one_or_none()
        if conn is None:
            conn = JiraConnection(
                id=_uid(),
                user_id=user.id,
                jira_url="https://demo.atlassian.net",
                jira_email=user.email,
                cloud_id="demo-cloud-id",
                is_active=True,
            )
            conn.access_token = "demo-access-token"
            db.add(conn)
            await db.flush()
            print("[OK] Created demo Jira connection.")
        else:
            print(f"[OK] Reusing existing Jira connection ({conn.id}).")

        # ── 3. Create projects ─────────────────────────────────────────────
        for (p_key, p_name, us_count, refined_count, risk_count,
             suite_defs, exec_defs) in PROJECTS:

            # idempotency check
            res = await db.execute(
                select(JiraProject)
                .where(
                    JiraProject.jira_connection_id == conn.id,
                    JiraProject.project_key == p_key,
                )
            )
            if res.scalar_one_or_none() is not None:
                print(f"[SKIP] Project {p_key} already exists — skipping.")
                continue

            proj = JiraProject(
                id=_uid(),
                jira_connection_id=conn.id,
                project_key=p_key,
                project_name=p_name,
            )
            db.add(proj)
            await db.flush()

            # ── User Stories ───────────────────────────────────────────────
            story_ids: list[str] = []
            for i in range(us_count):
                us_id = _uid()
                story_ids.append(us_id)
                us = UserStory(
                    id=us_id,
                    project_id=proj.id,
                    issue_key=f"{p_key}-{i + 1}",
                    title=f"[{p_key}] User story #{i + 1}",
                    description=f"Demo user story #{i + 1} for project {p_name}.",
                    acceptance_criteria=[f"AC1: system behaves correctly", f"AC2: error handled"],
                    current_score=round(0.65 + (i % 5) * 0.07, 2) if i < refined_count else None,
                    jira_status="In Progress" if i % 3 != 0 else "Done",
                    priority="High" if i % 4 == 0 else "Medium",
                )
                db.add(us)
            await db.flush()

            # ── Risks (one per story up to risk_count) ─────────────────────
            levels = ["low", "medium", "high", "critical"]
            depths = ["smoke", "standard", "thorough", "comprehensive"]
            for i in range(min(risk_count, us_count)):
                p_val = (i % 4) + 1
                i_val = ((i + 1) % 4) + 1
                score = p_val * i_val
                lvl_idx = 0 if score <= 5 else (1 if score <= 11 else (2 if score <= 19 else 3))
                db.add(Risk(
                    id=_uid(),
                    user_story_id=story_ids[i],
                    probability=p_val,
                    impact=i_val,
                    risk_score=score,
                    level=levels[lvl_idx],
                    description=f"Risk #{i + 1}: potential failure in {p_name} flow",
                    test_depth=depths[lvl_idx],
                    source="original",
                    is_ai_generated=True,
                    is_accepted=True,
                ))
            await db.flush()

            # ── Test Plan ─────────────────────────────────────────────────
            plan = TestPlan(
                id=_uid(),
                project_id=proj.id,
                title=f"{p_name} — Test Plan v1",
                description=f"AI-generated test plan for {p_name}.",
                status=TestPlanStatus.ACTIVE,
                approved_at=_ago(10),
                generation_completed_at=_ago(9),
            )
            db.add(plan)
            await db.flush()

            # ── Test Suites + Test Cases ───────────────────────────────────
            suite_ids: list[str] = []
            for s_idx, (suite_title, tc_count) in enumerate(suite_defs):
                suite = TestSuite(
                    id=_uid(),
                    test_plan_id=plan.id,
                    title=suite_title,
                    suite_type="functional",
                    priority="high" if s_idx == 0 else "medium",
                    is_ai_generated=True,
                    execution_order=s_idx + 1,
                    status=TestSuiteStatus.ACTIVE,
                )
                db.add(suite)
                await db.flush()
                suite_ids.append(suite.id)

                tc_types = ["positive", "negative", "edge_case"]
                for t in range(tc_count):
                    db.add(TestCase(
                        id=_uid(),
                        tc_code=_tc_code(),
                        title=f"{suite_title} — TC #{t + 1}",
                        test_plan_id=plan.id,
                        test_suite_id=suite.id,
                        user_story_id=story_ids[(t + s_idx) % us_count],
                        test_type=tc_types[t % 3],
                        is_active=True,
                    ))
                await db.flush()

            # ── Executions ────────────────────────────────────────────────
            for e_idx, (passed, failed) in enumerate(exec_defs):
                total = passed + failed
                suite_id = suite_ids[e_idx % len(suite_ids)]
                exec_obj = TestExecution(
                    id=_uid(),
                    suite_id=suite_id,
                    app_url="https://demo.app.local",
                    browser="chromium",
                    headless=True,
                    stop_on_failure=False,
                    status=TestExecutionStatus.COMPLETED,
                    total_count=total,
                    passed_count=passed,
                    failed_count=failed,
                    skipped_count=0,
                    error_count=0,
                    triggered_by=user.id,
                    is_closed=True,
                    started_at=_ago(20 - e_idx * 3),
                    completed_at=_ago(20 - e_idx * 3) + timedelta(minutes=15),
                )
                db.add(exec_obj)
            await db.flush()

            print(f"[OK] Created project {p_key}: {us_count} US, {risk_count} risks, "
                  f"{len(suite_defs)} suites, {len(exec_defs)} executions.")

        await db.commit()
        print("\nDone. Reload the dashboard to see the enriched data.")


# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    email = "rania.srl3@gmail.com"
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--email" and i + 1 < len(sys.argv[1:]):
            email = sys.argv[i + 2]
            break

    asyncio.run(seed(email))
