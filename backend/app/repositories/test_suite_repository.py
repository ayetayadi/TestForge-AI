"""TestSuite repository — async queries with full context loading."""

import logging
from typing import List, Optional, Dict, Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_suite import TestSuite
from app.models.test_case import TestCase
from app.models.test_case_dependency import TestCaseDependency
from app.models.test_plan import TestPlan
from app.models.jira_project import JiraProject
from app.models.risk import Risk
from app.models.user_story import UserStory

logger = logging.getLogger(__name__)


# ============================================================
# CLASSE REPOSITORY (utilisée par TestSuiteService)
# ============================================================

class TestSuiteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(
        self,
        plan_id: Optional[str] = None,
        project_id: Optional[str] = None,
        suite_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[TestSuite]:
        return await get_all_test_suites(self.db, plan_id, project_id, suite_type, status)

    async def get_by_id(self, suite_id: str) -> Optional[TestSuite]:
        return await get_test_suite_by_id(self.db, suite_id)

    async def get_risks_for_suite(self, suite: TestSuite) -> List[Risk]:
        return await get_risks_for_suite_func(self.db, suite)

    async def get_user_stories_for_suite(self, suite: TestSuite) -> List[UserStory]:
        return await get_user_stories_for_suite_func(self.db, suite)

    async def get_dependencies_for_suite(self, suite: TestSuite) -> List[TestCaseDependency]:
        return await get_deps_for_suite(self.db, suite)

    async def count_by_plan(self, plan_id: str) -> int:
        return await count_test_suites_by_plan(self.db, plan_id)


# ============================================================
# TEST SUITE CRUD
# ============================================================

async def get_all_test_suites(
    db: AsyncSession,
    plan_id: Optional[str] = None,
    project_id: Optional[str] = None,
    suite_type: Optional[str] = None,
    status: Optional[str] = None,
) -> List[TestSuite]:
    """Récupère toutes les suites avec leurs test cases et plan."""
    
    query = (
        select(TestSuite)
        .options(
            selectinload(TestSuite.test_cases),
            joinedload(TestSuite.test_plan).joinedload(TestPlan.jira_project),
        )
        .order_by(TestSuite.execution_order.asc().nullslast(), TestSuite.created_at.desc())
    )

    if plan_id:
        query = query.where(TestSuite.test_plan_id == plan_id)

    if project_id:
        query = query.join(TestPlan, TestSuite.test_plan_id == TestPlan.id).where(
            TestPlan.project_id == project_id
        )

    if suite_type:
        query = query.where(TestSuite.suite_type == suite_type)

    if status:
        query = query.where(TestSuite.status == status)

    result = await db.execute(query)
    return list(result.unique().scalars().all())


async def get_test_suite_by_id(
    db: AsyncSession, 
    suite_id: str
) -> Optional[TestSuite]:
    """Récupère une suite par ID avec toutes les relations."""
    
    query = (
        select(TestSuite)
        .where(TestSuite.id == suite_id)
        .options(
            selectinload(TestSuite.test_cases),
            joinedload(TestSuite.test_plan).joinedload(TestPlan.jira_project),
        )
    )
    result = await db.execute(query)
    return result.unique().scalar_one_or_none()


async def get_test_suites_by_plan_id(
    db: AsyncSession, 
    plan_id: str
) -> List[TestSuite]:
    """Récupère toutes les suites d'un plan."""
    
    query = (
        select(TestSuite)
        .where(TestSuite.test_plan_id == plan_id)
        .options(selectinload(TestSuite.test_cases))
        .order_by(TestSuite.execution_order.asc().nullslast())
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_test_suite(
    db: AsyncSession, 
    data: Dict[str, Any]
) -> TestSuite:
    """Crée une nouvelle suite de test."""
    
    suite = TestSuite(**data)
    db.add(suite)
    await db.commit()
    await db.refresh(suite)
    return suite


async def update_test_suite(
    db: AsyncSession, 
    suite_id: str, 
    data: Dict[str, Any]
) -> Optional[TestSuite]:
    """Met à jour une suite existante."""
    
    suite = await db.get(TestSuite, suite_id)
    if not suite:
        return None
    
    for key, value in data.items():
        if hasattr(suite, key):
            setattr(suite, key, value)
    
    await db.commit()
    await db.refresh(suite)
    return suite


async def delete_test_suite(
    db: AsyncSession, 
    suite_id: str
) -> bool:
    """Supprime une suite (les TCs deviennent orphelins)."""
    
    suite = await db.get(TestSuite, suite_id)
    if not suite:
        return False
    
    # Désassigner tous les TCs de cette suite
    tcs_result = await db.execute(
        select(TestCase).where(TestCase.test_suite_id == suite_id)
    )
    for tc in tcs_result.scalars().all():
        tc.test_suite_id = None
    
    await db.delete(suite)
    await db.commit()
    return True


async def count_test_suites_by_plan(
    db: AsyncSession, 
    plan_id: str
) -> int:
    """Compte le nombre de suites dans un plan."""
    
    result = await db.execute(
        select(func.count()).where(TestSuite.test_plan_id == plan_id)
    )
    return result.scalar_one() or 0


# ============================================================
# RISQUES & US (fonctions avec suffixe _func pour éviter conflit)
# ============================================================

async def get_risks_for_suite_func(
    db: AsyncSession,
    suite: TestSuite
) -> List[Risk]:
    """Récupère tous les risques liés aux TCs d'une suite."""
    
    tc_ids = [tc.id for tc in suite.test_cases] if suite.test_cases else []
    if not tc_ids:
        return []
    
    tcs_result = await db.execute(
        select(TestCase.user_story_id).where(
            TestCase.id.in_(tc_ids),
            TestCase.user_story_id.isnot(None)
        )
    )
    us_ids = list(set(row[0] for row in tcs_result))
    
    if not us_ids:
        return []
    
    result = await db.execute(
        select(Risk)
        .where(
            Risk.user_story_id.in_(us_ids),
            Risk.is_accepted == True
        )
        .order_by(Risk.risk_score.desc())
    )
    return list(result.scalars().all())


async def get_risks_for_suite(
    db: AsyncSession,
    suite: TestSuite
) -> List[Risk]:
    """Alias pour get_risks_for_suite_func."""
    return await get_risks_for_suite_func(db, suite)


async def get_user_stories_for_suite_func(
    db: AsyncSession,
    suite: TestSuite
) -> List[UserStory]:
    """Récupère toutes les US liées aux TCs d'une suite."""
    
    tc_ids = [tc.id for tc in suite.test_cases] if suite.test_cases else []
    if not tc_ids:
        return []
    
    tcs_result = await db.execute(
        select(TestCase.user_story_id)
        .where(
            TestCase.id.in_(tc_ids),
            TestCase.user_story_id.isnot(None)
        )
    )
    us_ids = list(set(row[0] for row in tcs_result))
    
    if not us_ids:
        return []
    
    result = await db.execute(
        select(UserStory).where(UserStory.id.in_(us_ids))
    )
    return list(result.scalars().all())


async def get_user_stories_for_suite(
    db: AsyncSession,
    suite: TestSuite
) -> List[UserStory]:
    """Alias pour get_user_stories_for_suite_func."""
    return await get_user_stories_for_suite_func(db, suite)


# ============================================================
# GRAPHE DE DÉPENDANCES
# ============================================================

async def get_deps_for_suite(
    db: AsyncSession,
    suite: TestSuite
) -> List[TestCaseDependency]:
    """Récupère toutes les dépendances où source OU target est dans la suite."""
    
    tc_ids = [tc.id for tc in suite.test_cases] if suite.test_cases else []
    if not tc_ids:
        return []
    
    result = await db.execute(
        select(TestCaseDependency)
        .where(
            or_(
                TestCaseDependency.source_test_case_id.in_(tc_ids),
                TestCaseDependency.target_test_case_id.in_(tc_ids)
            )
        )
        .options(
            selectinload(TestCaseDependency.source_test_case),
            selectinload(TestCaseDependency.target_test_case)
        )
    )
    return list(result.unique().scalars().all())


async def get_dependencies_for_suite(
    db: AsyncSession,
    suite: TestSuite
) -> List[TestCaseDependency]:
    """Alias pour get_deps_for_suite."""
    return await get_deps_for_suite(db, suite)


async def get_dependencies_for_plan(
    db: AsyncSession,
    plan_id: str
) -> List[TestCaseDependency]:
    """Récupère toutes les dépendances d'un plan."""
    
    result = await db.execute(
        select(TestCaseDependency)
        .where(TestCaseDependency.test_plan_id == plan_id)
        .options(
            selectinload(TestCaseDependency.source_test_case),
            selectinload(TestCaseDependency.target_test_case)
        )
        .order_by(TestCaseDependency.created_at.asc())
    )
    return list(result.unique().scalars().all())


async def create_dependency(
    db: AsyncSession,
    data: Dict[str, Any]
) -> TestCaseDependency:
    """Crée une dépendance entre deux TCs."""
    
    dep = TestCaseDependency(**data)
    db.add(dep)
    await db.commit()
    await db.refresh(dep)
    return dep


async def delete_dependency(
    db: AsyncSession,
    dep_id: str
) -> bool:
    """Supprime une dépendance."""
    
    dep = await db.get(TestCaseDependency, dep_id)
    if not dep:
        return False
    
    await db.delete(dep)
    await db.commit()
    return True


# ============================================================
# MATRICE DE TRAÇABILITÉ COMPLÈTE
# ============================================================

async def get_traceability_matrix(
    db: AsyncSession,
    plan_id: str
) -> Dict[str, Any]:
    """
    Construit la matrice de traçabilité pour un plan.
    """
    
    suites = await get_test_suites_by_plan_id(db, plan_id)
    
    all_tc_ids = []
    for suite in suites:
        if suite.test_cases:
            all_tc_ids.extend([tc.id for tc in suite.test_cases])
    
    if not all_tc_ids:
        return {
            "user_stories": [],
            "test_cases": [],
            "coverage": {"total_us": 0, "covered_us": 0, "coverage_pct": 0},
            "dependencies": []
        }
    
    tcs_result = await db.execute(
        select(TestCase)
        .where(TestCase.id.in_(all_tc_ids))
        .options(joinedload(TestCase.user_story))
    )
    all_tcs = list(tcs_result.unique().scalars().all())
    
    us_to_tcs: Dict[str, List[str]] = {}
    for tc in all_tcs:
        if tc.user_story_id:
            if tc.user_story_id not in us_to_tcs:
                us_to_tcs[tc.user_story_id] = []
            us_to_tcs[tc.user_story_id].append(tc.id)
    
    us_ids = list(us_to_tcs.keys())
    us_list = []
    if us_ids:
        us_result = await db.execute(
            select(UserStory).where(UserStory.id.in_(us_ids))
        )
        us_list = list(us_result.scalars().all())
    
    risks_list = []
    if us_ids:
        risks_result = await db.execute(
            select(Risk).where(
                Risk.user_story_id.in_(us_ids),
                Risk.is_accepted == True
            )
        )
        risks_list = list(risks_result.scalars().all())
    
    deps = await get_dependencies_for_plan(db, plan_id)
    
    plan = await db.get(TestPlan, plan_id)
    total_us = len(plan.scope_refs) if plan and plan.scope_refs else len(us_list)
    covered_us = len(us_to_tcs)
    coverage_pct = round((covered_us / total_us * 100) if total_us > 0 else 0, 1)
    
    return {
        "user_stories": [
            {
                "id": us.id,
                "issue_key": us.issue_key,
                "title": us.title,
                "sprint": us.sprint,
                "epic_name": us.epic_name,
                "test_case_ids": us_to_tcs.get(us.id, []),
                "test_case_count": len(us_to_tcs.get(us.id, [])),
                "risks": [
                    {
                        "id": r.id,
                        "description": r.description,
                        "level": r.level,
                        "risk_score": r.risk_score,
                    }
                    for r in risks_list if r.user_story_id == us.id
                ]
            }
            for us in us_list
        ],
        "test_cases": [
            {
                "id": tc.id,
                "tc_code": tc.tc_code,
                "title": tc.title,
                "test_type": tc.test_type,
                "priority": tc.priority,
                "user_story_id": tc.user_story_id,
                "suite_id": tc.test_suite_id,
            }
            for tc in all_tcs
        ],
        "coverage": {
            "total_us": total_us,
            "covered_us": covered_us,
            "coverage_pct": coverage_pct,
        },
        "dependencies": [
            {
                "id": dep.id,
                "source_tc_id": dep.source_test_case_id,
                "target_tc_id": dep.target_test_case_id,
                "dependency_type": dep.dependency_type,
                "source_tc_code": dep.source_test_case.tc_code if dep.source_test_case else None,
                "target_tc_code": dep.target_test_case.tc_code if dep.target_test_case else None,
            }
            for dep in deps
        ]
    }