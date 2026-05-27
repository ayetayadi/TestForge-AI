"""
Repository for TestCase CRUD operations and workflow-based generation.
"""

import re
import logging
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy import select, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.test_case import TestCase
from app.models.test_suite import TestSuite
from app.models.test_plan import TestPlan
from app.models.jira_project import JiraProject
from app.models.user_story import UserStory
from app.models.risk import Risk

logger = logging.getLogger(__name__)

_TC_CODE_PATTERN = re.compile(r"^TC-(\d{3})$")

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

async def generate_unique_tc_code(db: AsyncSession) -> str:
    """Génère un code TC unique globalement. Format: TC-XXX (incrémental)."""
    result = await db.execute(
        text("SELECT MAX(CAST(SUBSTRING(tc_code FROM 4) AS INTEGER)) FROM test_cases")
    )
    max_number = result.scalar()
    
    if max_number is None:
        return "TC-001"
    
    next_number = max_number + 1
    while True:
        code = f"TC-{next_number:03d}"
        check = await db.execute(
            text("SELECT 1 FROM test_cases WHERE tc_code = :code"),
            {"code": code}
        )
        if not check.fetchone():
            return code
        next_number += 1


# ============================================================
# CRUD OPERATIONS
# ============================================================

async def get_all_test_cases(
    db: AsyncSession,
    test_suite_id: Optional[str] = None,
    test_plan_id: Optional[str] = None,
    project_id: Optional[str] = None,
    project_ids: Optional[List[str]] = None,
    search: Optional[str] = None,
    status: Optional[List[str]] = None,
    priority: Optional[List[str]] = None,
    has_script: Optional[bool] = None,
    order_by: str = "tc_code",
    order_direction: str = "asc",
    limit: int = 100,
    offset: int = 0
) -> List[TestCase]:
    """Récupère tous les test cases avec filtres."""

    query = select(TestCase).options(joinedload(TestCase.user_story),
        joinedload(TestCase.test_plan).joinedload(TestPlan.jira_project),
        joinedload(TestCase.test_suite),
    )

    if test_plan_id:
        query = query.where(TestCase.test_plan_id == test_plan_id)

    if test_suite_id:
        query = query.where(TestCase.test_suite_id == test_suite_id)

    if project_ids is not None:
        query = query.join(TestPlan, TestCase.test_plan_id == TestPlan.id)
        query = query.where(TestPlan.project_id.in_(project_ids))
    elif project_id:
        query = query.join(TestPlan, TestCase.test_plan_id == TestPlan.id)
        query = query.where(TestPlan.project_id == project_id)

    if search:
        query = query.where(
            or_(
                TestCase.title.ilike(f"%{search}%"),
                TestCase.tc_code.ilike(f"%{search}%")
            )
        )

    # Status filter
    if status:
        if 'active' in status and 'archived' not in status:
            query = query.where(TestCase.is_active == True)
        elif 'archived' in status and 'active' not in status:
            query = query.where(TestCase.is_active == False)
    else:
        query = query.where(TestCase.is_active == True)
    
    if priority:
        query = query.where(TestCase.priority.in_([p.lower() for p in priority]))

    
    # Ordering
    order_mapping = {
        "tc_code": TestCase.tc_code,
        "created_at": TestCase.created_at,
        "updated_at": TestCase.updated_at,
        "title": TestCase.title,
        "execution_order": TestCase.execution_order,
    }
    order_col = order_mapping.get(order_by, TestCase.created_at)
    
    if order_direction.lower() == "asc":
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())
    
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.unique().scalars().all()


async def count_all_test_cases(
    db: AsyncSession,
    test_suite_id: Optional[str] = None,
    test_plan_id: Optional[str] = None,
    project_id: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[List[str]] = None,
    priority: Optional[List[str]] = None,
) -> int:
    """Compte le nombre total de test cases avec filtres."""
    
    query = select(func.count(TestCase.id)).where(TestCase.is_active == True)

    if test_plan_id:
        query = query.where(TestCase.test_plan_id == test_plan_id)  # ✅ Direct

    if test_suite_id:
        query = query.where(TestCase.test_suite_id == test_suite_id)

    if project_id:
        query = query.join(TestPlan, TestCase.test_plan_id == TestPlan.id)
        query = query.where(TestPlan.project_id == project_id)
    
    if search:
        query = query.where(
            or_(
                TestCase.title.ilike(f"%{search}%"),
                TestCase.tc_code.ilike(f"%{search}%")
            )
        )
    
    if status:
        if 'active' in status and 'archived' not in status:
            query = query.where(TestCase.is_active == True)
        elif 'archived' in status and 'active' not in status:
            query = query.where(TestCase.is_active == False)
    
    if priority:
        query = query.where(TestCase.priority.in_([p.lower() for p in priority]))

    
    result = await db.execute(query)
    return result.scalar()


async def get_test_case_by_id(db: AsyncSession, test_case_id: str) -> Optional[TestCase]:
    """Récupère un test case par son ID avec eager loading complet."""
    result = await db.execute(
        select(TestCase)
        .where(TestCase.id == test_case_id)
        .options(joinedload(TestCase.user_story),
            joinedload(TestCase.test_plan).joinedload(TestPlan.jira_project),
            joinedload(TestCase.test_suite),
        )
    )
    return result.scalar_one_or_none()


async def get_test_case_by_code(db: AsyncSession, tc_code: str) -> Optional[TestCase]:
    """Récupère un test case par son code (TC-XXX)."""
    result = await db.execute(
        select(TestCase)
        .where(TestCase.tc_code == tc_code)
        .options(
            joinedload(TestCase.user_story),
            joinedload(TestCase.test_plan).joinedload(TestPlan.jira_project),
            joinedload(TestCase.test_suite),
        )
    )
    return result.scalar_one_or_none()


async def get_test_cases_by_ids(db: AsyncSession, ids: List[str]) -> List[TestCase]:
    """Fetch multiple test cases by their IDs."""
    if not ids:
        return []
    result = await db.execute(
        select(TestCase).where(TestCase.id.in_(ids))
    )
    return list(result.scalars().all())


async def get_test_cases_by_test_suite_id(db: AsyncSession, test_suite_id: str) -> List[TestCase]:
    """Récupère tous les test cases d'une suite."""
    result = await db.execute(
        select(TestCase)
        .where(TestCase.test_suite_id == test_suite_id)
        .where(TestCase.is_active == True)
        .options(joinedload(TestCase.user_story),
            joinedload(TestCase.test_plan).joinedload(TestPlan.jira_project),
            joinedload(TestCase.test_suite),
        )
        .order_by(TestCase.tc_code.asc().nulls_last())
    )
    return result.unique().scalars().all()


async def get_test_cases_by_test_plan_id(
    db: AsyncSession, 
    test_plan_id: str
) -> List[TestCase]:
    """Récupère les TC liés DIRECTEMENT à un Test Plan."""
    result = await db.execute(
        select(TestCase)
        .where(
            TestCase.test_plan_id == test_plan_id,  # ✅ Direct
            TestCase.is_active == True,
        )
        .options(joinedload(TestCase.user_story),
            joinedload(TestCase.test_plan).joinedload(TestPlan.jira_project),
            joinedload(TestCase.test_suite),
        )
        .order_by(TestCase.tc_code.asc().nulls_last())
    )
    return result.unique().scalars().all()


async def create_test_case(db: AsyncSession, data: dict) -> TestCase:
    """Crée un nouveau test case avec code unique si non fourni."""
    if 'tc_code' not in data or not data['tc_code']:
        data['tc_code'] = await generate_unique_tc_code(db)
    
    test_case = TestCase(**data)
    db.add(test_case)
    await db.flush()
    return test_case


async def update_test_case(db: AsyncSession, test_case_id: str, data: dict) -> Optional[TestCase]:
    """Met à jour un test case."""
    test_case = await get_test_case_by_id(db, test_case_id)
    if test_case:
        for key, value in data.items():
            if hasattr(test_case, key) and value is not None:
                setattr(test_case, key, value)
        await db.flush()
    return test_case


async def delete_test_case(db: AsyncSession, test_case_id: str) -> bool:
    """Supprime un test case (soft delete)."""
    test_case = await get_test_case_by_id(db, test_case_id)
    if test_case:
        test_case.is_active = False
        await db.flush()
        return True
    return False


async def batch_create_test_cases(
    db: AsyncSession,
    test_cases_data: List[dict],
) -> List[TestCase]:
    """Persist a list of test case dicts to the database."""
    created: List[TestCase] = []
    for data in test_cases_data:
        try:
            desired_code = data.get("tc_code", "")
            
            if desired_code:
                existing = await db.execute(
                    select(TestCase).where(TestCase.tc_code == desired_code)
                )
                if existing.scalar_one_or_none():
                    logger.info("[TC_REPO] tc_code '%s' already taken, generating new one", desired_code)
                    desired_code = ""
            
            if not desired_code:
                data["tc_code"] = await generate_unique_tc_code(db)
            else:
                data["tc_code"] = desired_code
            
            async with db.begin_nested():
                tc = TestCase(**data)
                db.add(tc)
                await db.flush()
            created.append(tc)
            
        except Exception as exc:
            logger.warning("[TC_REPO] Skipping TC: %s", str(exc)[:200])
    return created


# ============================================================
# COVERAGE
# ============================================================

async def count_suites_with_tc(db: AsyncSession, test_plan_id: str) -> Tuple[int, int]:
    """Return (covered_suites_count, total_suites_count) for a Test Plan."""
    total_result = await db.execute(
        select(func.count(TestSuite.id)).where(TestSuite.test_plan_id == test_plan_id)
    )
    total_suites = total_result.scalar() or 0

    covered_result = await db.execute(
        select(func.count(func.distinct(TestSuite.id)))
        .join(TestCase, TestCase.test_suite_id == TestSuite.id)
        .where(
            TestSuite.test_plan_id == test_plan_id,
            TestCase.is_active == True,
        )
    )
    covered_suites = covered_result.scalar() or 0

    return covered_suites, total_suites