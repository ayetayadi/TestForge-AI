"""
Service for TestCase CRUD operations and workflow-based generation.
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any, Callable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.repositories import test_case_repository as repo
from app.models.test_case import TestCase
from app.models.test_suite import TestSuite
from app.models.test_plan import TestPlan
from app.models.jira_project import JiraProject
from app.models.user_story import UserStory
from app.models.user_story_version import UserStoryVersion
from app.models.risk import Risk
from app.models.tc_coverage import TcCoverage
from app.models.enums import StoryDecision
from app.ai_workflows.test_case import get_pipeline
from app.ai_workflows.test_case.test_case_builder import build_tc_code

logger = logging.getLogger(__name__)


# ============================================================
# CRUD OPERATIONS
# ============================================================

async def get_all_test_cases(
    db: AsyncSession,
    test_suite_id: Optional[str] = None,
    test_plan_id: Optional[str] = None,
    project_id: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[List[str]] = None,
    priority: Optional[List[str]] = None,
    order_by: str = "created_at",
    order_direction: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Récupère tous les test cases avec filtres."""
    
    items = await repo.get_all_test_cases(
        db,
        test_suite_id=test_suite_id,
        test_plan_id=test_plan_id,
        project_id=project_id,
        search=search,
        status=status,
        priority=priority,
        order_by=order_by,
        order_direction=order_direction,
        limit=limit,
        offset=offset,
    )
    
    formatted_items = []
    for item in items:
        formatted = await format_for_frontend(item, db)
        formatted_items.append(formatted)
    
    return formatted_items


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
    return await repo.count_all_test_cases(
        db,
        test_suite_id=test_suite_id,
        test_plan_id=test_plan_id,
        project_id=project_id,
        search=search,
        status=status,
        priority=priority,
    )


async def get_test_case_by_id(db: AsyncSession, test_case_id: str) -> Optional[TestCase]:
    """Récupère un test case par son ID."""
    return await repo.get_test_case_by_id(db, test_case_id)


async def get_test_case_by_code(db: AsyncSession, tc_code: str) -> Optional[TestCase]:
    """Récupère un test case par son code."""
    return await repo.get_test_case_by_code(db, tc_code)


async def get_test_cases_by_test_suite(db: AsyncSession, test_suite_id: str) -> List[TestCase]:
    """Récupère tous les test cases d'une suite."""
    return await repo.get_test_cases_by_test_suite_id(db, test_suite_id)


async def get_test_cases_by_test_plan(db: AsyncSession, test_plan_id: str) -> List[TestCase]:
    """Récupère tous les test cases d'un plan (via les suites)."""
    return await repo.get_test_cases_by_test_plan_id(db, test_plan_id)


async def create_test_case(db: AsyncSession, data: Dict[str, Any]) -> TestCase:
    """Crée un nouveau test case (test_suite_id optionnel)."""
    if not data.get("title"):
        raise ValueError("title is required")
    
    if data.get("test_suite_id"):
        suite = await db.get(TestSuite, data["test_suite_id"])
        if not suite:
            raise ValueError("TestSuite not found")
    
    return await repo.create_test_case(db, data)


async def update_test_case(db: AsyncSession, test_case_id: str, data: Dict[str, Any]) -> Optional[TestCase]:
    """Met à jour un test case."""
    return await repo.update_test_case(db, test_case_id, data)


async def delete_test_case(db: AsyncSession, test_case_id: str) -> bool:
    """Supprime (soft delete) un test case."""
    return await repo.delete_test_case(db, test_case_id)


# ============================================================
# WORKFLOW GENERATION
# ============================================================
async def generate_test_cases_for_plan(
    db: AsyncSession,
    test_plan_id: str,
    test_suite_id: Optional[str] = None,
    risk_level: Optional[str] = None,
    risk_score: Optional[float] = None,
    risk_description: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
    scenario_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate TCs for a TestPlan - PARALLEL per US."""
    
    # 1. Load TestPlan
    test_plan = await db.get(TestPlan, test_plan_id)
    if not test_plan:
        raise ValueError(f"Test plan '{test_plan_id}' not found")
    
    project_id = test_plan.project_id

    # 2. Load accepted risks
    risk_query = (
        select(Risk)
        .join(UserStory, Risk.user_story_id == UserStory.id)
        .where(UserStory.project_id == project_id, Risk.is_accepted == True)
    )
    risk_result = await db.execute(risk_query)
    accepted_risks = risk_result.scalars().all()
    
    if not accepted_risks:
        raise ValueError("No accepted risks found for this project. Accept risks first.")
    
    risk_ids = [r.id for r in accepted_risks]
    
    # 3. Determine risk level
    levels = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    highest_risk = max(accepted_risks, key=lambda r: levels.get(r.level, 0))
    effective_risk_level = risk_level or highest_risk.level
    effective_risk_score = risk_score or _score_from_level(effective_risk_level)

    # 4. Récupérer les US selon le scope_type
    scope_refs = test_plan.scope_refs or []
    scope_type = test_plan.scope_type or "manual"
    
    us_list = []
    if scope_refs:
        if scope_type == "sprint":
            us_result = await db.execute(
                select(UserStory).where(UserStory.sprint.in_(scope_refs), UserStory.project_id == project_id)
            )
        elif scope_type == "epic":
            us_result = await db.execute(
                select(UserStory).where(
                    or_(UserStory.epic_key.in_(scope_refs), UserStory.epic_name.in_(scope_refs)),
                    UserStory.project_id == project_id
                )
            )
        else:
            us_result = await db.execute(
                select(UserStory).where(UserStory.issue_key.in_(scope_refs), UserStory.project_id == project_id)
            )
        us_list = us_result.scalars().all()
    
    # Si scope_refs est vide, prendre TOUTES les US du projet
    else:
        us_result = await db.execute(
            select(UserStory).where(UserStory.project_id == project_id)
        )
        us_list = us_result.scalars().all()

    logger.info(f"[TC_GEN] us_list count: {len(us_list)}")

    if not us_list:
        raise ValueError("No user stories found in the test plan scope.")

    # Default to positive if no type provided
    effective_scenario_type = scenario_type or "positive"

    # ============================================================
    # Helper: generate TCs for a single US
    # ============================================================
    async def _generate_for_single_us(us: UserStory) -> Dict[str, Any]:
        """Generate TCs for a single user story (used in parallel)."""
        approved_result = await db.execute(
            select(UserStoryVersion)
            .where(UserStoryVersion.user_story_id == us.id, UserStoryVersion.decision_status == StoryDecision.APPROVED)
            .order_by(UserStoryVersion.version_number.desc()).limit(1)
        )
        approved = approved_result.scalar_one_or_none()

        if approved and approved.improved_story:
            story_text = approved.improved_story
            ac_list = approved.generated_acceptance_criteria or []
        else:
            story_text = us.description or us.title or ""
            ac_list = us.acceptance_criteria or []

        logger.info(f"[TC_GEN] Generating '{effective_scenario_type}' TCs for {us.issue_key} ({len(ac_list)} ACs)...")

        pipeline = get_pipeline()
        
        risks_result = await db.execute(
        select(Risk).where(
                Risk.user_story_id == us.id,
                Risk.is_accepted == True
            )
        )
        us_risks = risks_result.scalars().all()
        
        risk_mitigation = " | ".join([r.mitigation for r in us_risks if r.mitigation]) or "N/A"
        result = await pipeline.run(
            story=story_text,
            acceptance_criteria=[str(ac).strip() for ac in ac_list if ac and str(ac).strip()],
            risk_level=effective_risk_level,
            risk_score=effective_risk_score,
            risk_description=risk_description or _build_risk_description(risk_ids),
            risk_mitigation=risk_mitigation,
            risk_ids=risk_ids,
            user_story_id=us.id,
            issue_key=us.issue_key,
            tc_start_index=1,
            progress_callback=progress_callback,
            scenario_type=effective_scenario_type,
        )
        ac_cov = result.get("ac_coverage", {})

        # Upsert coverage record for this (plan, us, type)
        await _upsert_tc_coverage(
            db=db,
            test_plan_id=test_plan_id,
            user_story_id=us.id,
            issue_key=us.issue_key,
            user_story_title=us.title,
            scenario_type=effective_scenario_type,
            ac_coverage=ac_cov,
            tc_count=len(result.get("test_cases", [])),
        )

        return result
    
    # ============================================================
    # LANCER TOUTES LES GÉNÉRATIONS EN PARALLÈLE
    # ============================================================
    total_us = len(us_list)
    if progress_callback:
        await progress_callback("tc_init", {"total_us": total_us, "message": f"Starting generation for {total_us} user stories..."})

    completed_us_count = 0

    async def _generate_with_progress(us: UserStory) -> Dict[str, Any]:
        nonlocal completed_us_count
        result = await _generate_for_single_us(us)
        completed_us_count += 1
        if progress_callback:
            await progress_callback("us_done", {
                "completed": completed_us_count,
                "total": total_us,
                "issue_key": us.issue_key,
                "count": len(result.get("test_cases", [])) if not isinstance(result, Exception) else 0,
            })
        return result

    # Séquentiel
    results = []
    for us in us_list:
        result = await _generate_with_progress(us)
        results.append(result)
    
    # ============================================================
    # ASSEMBLER LES RÉSULTATS
    # ============================================================
    all_tcs = []
    tc_index = 1
    
    for i, result in enumerate(results):
        us = us_list[i]
        
        if isinstance(result, Exception):
            logger.error(f"[TC_GEN] Failed for {us.issue_key}: {result}", exc_info=True)
            continue
        
        if result.get("workflow_status") == "error":
            logger.error(f"[TC_GEN] Failed for {us.issue_key}: {result.get('error')}")
            continue
        
        us_tcs = result.get("test_cases", [])
        
        # Réassigner les tc_code avec les bons indices séquentiels
        for tc in us_tcs:
            tc["tc_code"] = build_tc_code(tc_index)  # ou format "TC-{tc_index:04d}"
            tc_index += 1
        
        all_tcs.extend(us_tcs)
        logger.info(f"[TC_GEN] {us.issue_key}: generated {len(us_tcs)} TCs")
    
    # 6. Persist ALL TCs
    if not all_tcs:
        return {
            "test_cases": [], "count": 0,
            "test_plan_id": test_plan_id, "test_suite_id": test_suite_id,
            "workflow_status": "success",
            "feature_gherkin": "", "coverage": {}, "coverage_hints": [],
        }
    
    db_data = [_pipeline_tc_to_db(tc, test_plan_id, test_suite_id) for tc in all_tcs]
    created = await repo.batch_create_test_cases(db, db_data)
    
    logger.info(f"[TC_GEN] Persisted {len(created)}/{len(all_tcs)} TCs for plan={test_plan.title}")
    
    return {
        "test_cases": [_db_tc_to_response(tc) for tc in created],
        "count": len(created),
        "feature_gherkin": "",
        "coverage": {},
        "coverage_hints": [],
        "test_plan_id": test_plan_id,
        "test_suite_id": test_suite_id,
        "workflow_status": "success",
    }

# ============================================================
# HELPERS
# ============================================================

async def format_for_frontend(test_case: TestCase, db: AsyncSession) -> Dict[str, Any]:
    """Formate un test case avec infos suite/plan/projet/US/risks/version."""
    
    suite_info = {}
    plan_info = {}
    us_info = {}
    version_info = {}
    risks_info = []
    
    # 1. Suite (si assignée)
    if test_case.test_suite_id:
        suite = await db.get(TestSuite, test_case.test_suite_id)
        if suite:
            suite_info["test_suite_title"] = suite.title
    
    # 2. Plan via relationship (eager loaded)
    plan = test_case.test_plan
    if not plan and test_case.test_plan_id:
        plan = await db.get(TestPlan, test_case.test_plan_id)
    
    if plan:
        plan_info["test_plan_id"] = plan.id
        plan_info["test_plan_title"] = plan.title
        plan_info["project_id"] = plan.project_id
        
        # Projet
        project = plan.jira_project
        if not project:
            project = await db.get(JiraProject, plan.project_id)
        if project:
            plan_info["project_name"] = project.project_name
    
    # 3. US directement via la relationship
    us = test_case.user_story
    if not us and test_case.user_story_id:
        us = await db.get(UserStory, test_case.user_story_id)
    
    if us:
        us_info = {
            "user_story_id": us.id,
            "issue_key": us.issue_key,
            "user_story_title": us.title,
            "user_story_description": us.description,
            "sprint": us.sprint,
            "epic_key": us.epic_key,
            "epic_name": us.epic_name,
        }
        
        # ============================================
        # RÉCUPÉRER LES RISQUES LIÉS À CETTE US
        # ============================================
        risks_result = await db.execute(
            select(Risk).where(
                Risk.user_story_id == us.id,
                Risk.is_accepted == True
            ).order_by(Risk.level.desc())
        )
        us_risks = risks_result.scalars().all()
        
        for risk in us_risks:
            risks_info.append({
                "id": risk.id,
                "description": risk.description,
                "mitigation": risk.mitigation,
                "probability": risk.probability,
                "impact": risk.impact,
                "risk_score": risk.risk_score,
                "level": risk.level,
                "is_accepted": risk.is_accepted,
                "is_ai_generated": risk.is_ai_generated,
                "source": risk.source,  # "original" ou "approved_version"
                "source_story_text": risk.source_story_text,
                "created_at": risk.created_at.isoformat() if risk.created_at else None,
            })
        
        # ============================================
        # ✅ VÉRIFIER LA VERSION APPROUVÉE
        # ============================================
        approved_result = await db.execute(
            select(UserStoryVersion)
            .where(
                UserStoryVersion.user_story_id == us.id,
                UserStoryVersion.decision_status == StoryDecision.APPROVED
            )
            .order_by(UserStoryVersion.version_number.desc())
            .limit(1)
        )
        approved_version = approved_result.scalar_one_or_none()
        
        if approved_version:
            version_info = {
                "id": approved_version.id,
                "version_number": approved_version.version_number,
                "decision_status": approved_version.decision_status.value if approved_version.decision_status else "pending",
                "improved_story": approved_version.improved_story,
                "final_score": approved_version.final_score,
                "testability_score": approved_version.testability_score,
                "is_testable": approved_version.is_testable,
                "started_at": approved_version.started_at.isoformat() if approved_version.started_at else None,
                "completed_at": approved_version.completed_at.isoformat() if approved_version.completed_at else None,
            }
            
            # ✅ Déterminer quelle story est utilisée
            story_source = "approved"
            story_text_used = approved_version.improved_story
            ac_used = approved_version.generated_acceptance_criteria or []
            version_number_used = approved_version.version_number
        else:
            story_source = "original"
            story_text_used = us.description or us.title or ""
            ac_used = us.acceptance_criteria or []
            version_number_used = None
    
    # ============================================
    # ✅ CONSTRUIRE L'OBJET STORY DETAILS
    # ============================================
    story_details = {
        "source": story_source if us else None,
        "version_number": version_number_used if us else None,
        "story_text": story_text_used if us else None,
        "acceptance_criteria": ac_used if us else [],
        "has_approved_version": bool(version_info) if us else False,
        "approved_version": version_info if version_info else None,
    }
    
    return {
        "id": test_case.id,
        "tc_code": test_case.tc_code,
        "title": test_case.title,
        "description": test_case.description,
        "test_type": test_case.test_type,
        "priority": test_case.priority,
        "test_suite_id": test_case.test_suite_id,
        "test_suite_title": suite_info.get("test_suite_title"),
        "test_plan_id": plan_info.get("test_plan_id", test_case.test_plan_id),
        "test_plan_title": plan_info.get("test_plan_title"),
        "project_id": plan_info.get("project_id"),
        "project_name": plan_info.get("project_name"),
        "user_story_id": us_info.get("user_story_id", test_case.user_story_id),
        "issue_key": us_info.get("issue_key"),
        "user_story_title": us_info.get("user_story_title"),
        "sprint": us_info.get("sprint"),
        "epic_key": us_info.get("epic_key"),
        "epic_name": us_info.get("epic_name"),
        
        "story_details": story_details,
        "risks": risks_info,
        "risks_count": len(risks_info),
        
        "preconditions": test_case.preconditions,
        "postconditions": test_case.postconditions,
        "steps": test_case.steps,
        "gherkin_source": test_case.gherkin_source,
        "test_data": test_case.test_data,
        "expected_results": test_case.expected_results,
        "locators": test_case.locators,
        "is_active": test_case.is_active,
        "created_at": test_case.created_at.isoformat() if test_case.created_at else None,
        "updated_at": test_case.updated_at.isoformat() if test_case.updated_at else None,
    }

# ============================================================
# COVERAGE HELPERS
# ============================================================

async def _upsert_tc_coverage(
    db: AsyncSession,
    test_plan_id: str,
    user_story_id: str,
    issue_key: Optional[str],
    user_story_title: Optional[str],
    scenario_type: str,
    ac_coverage: Dict[str, Any],
    tc_count: int,
) -> None:
    """Insert or update the coverage row for (test_plan, user_story, scenario_type)."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    values = {
        "id": str(__import__("uuid").uuid4()),
        "test_plan_id": test_plan_id,
        "user_story_id": user_story_id,
        "issue_key": issue_key,
        "user_story_title": user_story_title,
        "scenario_type": scenario_type,
        "coverage_pct": ac_coverage.get("coverage_pct", 0.0),
        "covered_count": ac_coverage.get("covered_count", 0),
        "total_ac_count": ac_coverage.get("total_count", 0),
        "tc_count": tc_count,
    }

    stmt = pg_insert(TcCoverage).values(**values).on_conflict_do_update(
        constraint="uq_tc_coverage",
        set_={
            "coverage_pct": values["coverage_pct"],
            "covered_count": values["covered_count"],
            "total_ac_count": values["total_ac_count"],
            "tc_count": values["tc_count"],
            "issue_key": values["issue_key"],
            "user_story_title": values["user_story_title"],
        },
    )
    await db.execute(stmt)


async def get_tc_coverage_for_plan(db: AsyncSession, test_plan_id: str) -> List[Dict[str, Any]]:
    """Return all coverage rows for a given test plan, ordered by issue_key + scenario_type."""
    result = await db.execute(
        select(TcCoverage)
        .where(TcCoverage.test_plan_id == test_plan_id)
        .order_by(TcCoverage.issue_key, TcCoverage.scenario_type)
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "test_plan_id": r.test_plan_id,
            "user_story_id": r.user_story_id,
            "issue_key": r.issue_key,
            "user_story_title": r.user_story_title,
            "scenario_type": r.scenario_type,
            "coverage_pct": round(r.coverage_pct * 100, 1),
            "covered_count": r.covered_count,
            "total_ac_count": r.total_ac_count,
            "tc_count": r.tc_count,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        }
        for r in rows
    ]


def _score_from_level(level: str) -> float:
    return {"critical": 4.0, "high": 3.0, "medium": 1.5, "low": 0.5}.get(level, 1.5)


def _build_risk_description(risk_ids: List[str]) -> str:
    if not risk_ids:
        return "N/A"
    return f"{len(risk_ids)} accepted risk(s) linked to this project"


def _pipeline_tc_to_db(tc: Dict[str, Any], test_plan_id: str, test_suite_id: Optional[str] = None) -> Dict[str, Any]:
    """Map a finalized pipeline TC dict to the TestCase ORM field set."""
    return {
        "tc_code":         tc.get("tc_code", ""),
        "title":           tc.get("title", ""),
        "description":     tc.get("description"),
        "test_type":       tc.get("test_type", "positive"),
        "priority":        tc.get("priority", "medium"),
        "preconditions":   tc.get("preconditions", []),
        "postconditions":  tc.get("postconditions", []),
        "gherkin_source":  tc.get("gherkin_source", ""),
        "steps":           tc.get("steps", []),
        "test_data":       tc.get("test_data") or {},
        "expected_results": tc.get("expected_results", []),
        "user_story_id":   tc.get("user_story_id"), 
        "test_plan_id":    test_plan_id,
        "test_suite_id":   test_suite_id,
        "execution_order": tc.get("execution_order"),
        "is_active":       True,
        "_covered_ac_indices": tc.get("_covered_ac_indices", []),
        "_reasoning": tc.get("_reasoning", ""),
    }


def _db_tc_to_response(tc) -> Dict[str, Any]:
    """Serialize a TestCase ORM object for the API response."""
    return {
        "id":              tc.id,
        "tc_code":         tc.tc_code,
        "title":           tc.title,
        "test_type":       tc.test_type,
        "priority":        tc.priority,
        "preconditions":   tc.preconditions or [],
        "postconditions":  tc.postconditions or [],
        "gherkin_source":  tc.gherkin_source,
        "steps":           tc.steps or [],
        "test_data":       tc.test_data or {},
        "expected_results": tc.expected_results or [],
        "test_plan_id":    tc.test_plan_id,
        "test_suite_id":   tc.test_suite_id,
        "execution_order": tc.execution_order,
        "is_active":       tc.is_active,
        "created_at":      tc.created_at.isoformat() if tc.created_at else None,
        "updated_at":      tc.updated_at.isoformat() if tc.updated_at else None,
    }