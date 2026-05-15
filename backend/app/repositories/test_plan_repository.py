"""TestPlan repository — async CRUD + statistics with sprint/epic filtering."""

import logging
import math
from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_plan import TestPlan
from app.models.jira_project import JiraProject
from app.models.user_story import UserStory
from app.models.risk import Risk
from app.schemas.test_plan_schema import TestPlanCreate, TestPlanUpdate

logger = logging.getLogger(__name__)


class TestPlanRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============================================================
    # CREATE
    # ============================================================

    async def create(self, data: TestPlanCreate) -> TestPlan:
        """Crée un Test Plan pour un projet, avec filtres sprint/epic optionnels."""
        await self._validate_project(data.project_id)

        # Vérifie que les User Stories ciblées ont des risques acceptés
        if data.require_accepted_risks:
            await self._validate_accepted_risks(
                data.project_id,
                data.sprint_ids,
                data.epic_keys
            )

        plan = TestPlan(
            id=str(uuid4()),
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            objective=data.objective,
            scope_type=data.scope_type,
            scope_refs=data.scope_refs or [],
            in_scope=data.in_scope,
            out_of_scope=data.out_of_scope,
            environment=data.environment,
            start_date=data.start_date,
            end_date=data.end_date,
            entry_criteria=data.entry_criteria,
            exit_criteria=data.exit_criteria,
            approach=data.approach,
            assumptions=data.assumptions,
            constraints=data.constraints,
            stakeholders=data.stakeholders,
            communication=data.communication,
            risk_analysis=data.risk_analysis,
            
        )

        self.db.add(plan)
        await self.db.flush()
        await self.db.refresh(plan)

        logger.info(
            f"[TEST PLAN REPO] Created plan {plan.id} for project {data.project_id}"
            f" | sprints={data.sprint_ids} | epics={data.epic_keys}"
        )
        return plan

    # ============================================================
    # READ
    # ============================================================

    async def get_by_id(self, plan_id: str) -> Optional[TestPlan]:
        result = await self.db.execute(
            select(TestPlan)
            .options(selectinload(TestPlan.jira_project))
            .where(TestPlan.id == plan_id)
        )
        return result.scalar_one_or_none()

    async def get_by_project(
        self,
        project_id: str,
        sprint_ids: Optional[List[str]] = None,
        epic_keys: Optional[List[str]] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[TestPlan], int]:
        """Récupère les Test Plans d'un projet avec filtres sprint/epic optionnels."""
        
        base = select(TestPlan).where(TestPlan.project_id == project_id)

        # Filtre par sprint (cherche dans scope_refs JSONB)
        if sprint_ids:
            conditions = []
            for sprint_id in sprint_ids:
                conditions.append(TestPlan.scope_refs.contains([sprint_id]))
            base = base.where(or_(*conditions))

        # Filtre par epic (cherche dans scope_refs JSONB)
        if epic_keys:
            conditions = []
            for epic_key in epic_keys:
                conditions.append(TestPlan.scope_refs.contains([epic_key]))
            base = base.where(or_(*conditions))

        # Count
        count_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar_one()

        # Pagination
        offset = (page - 1) * page_size
        result = await self.db.execute(
            base.options(selectinload(TestPlan.jira_project))
            .order_by(TestPlan.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = list(result.scalars().all())

        return items, total

    async def get_all(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        project_ids: Optional[List[str]] = None,
    ) -> Tuple[List[TestPlan], int]:
        """Récupère tous les Test Plans avec filtres optionnels."""

        base = select(TestPlan).options(selectinload(TestPlan.jira_project))

        if project_ids is not None:
            base = base.where(TestPlan.project_id.in_(project_ids))
        elif project_id:
            base = base.where(TestPlan.project_id == project_id)
        if status:
            base = base.where(TestPlan.status == status)

        # Count
        count_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar_one()

        # Pagination
        offset = (page - 1) * page_size
        result = await self.db.execute(
            base.order_by(TestPlan.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = list(result.scalars().all())

        return items, total

    async def get_latest_by_project(self, project_id: str) -> Optional[TestPlan]:
        result = await self.db.execute(
            select(TestPlan)
            .where(TestPlan.project_id == project_id)
            .order_by(TestPlan.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ============================================================
    # UPDATE
    # ============================================================

    async def update(self, plan_id: str, data: TestPlanUpdate) -> Optional[TestPlan]:
        plan = await self.get_by_id(plan_id)
        if not plan:
            return None

        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(plan, field, value)

        await self.db.flush()
        await self.db.refresh(plan)

        logger.info(f"[TEST PLAN REPO] Updated plan {plan_id}: {list(updates.keys())}")
        return plan

    async def set_status(self, plan_id: str, status: str) -> Optional[TestPlan]:
        plan = await self.get_by_id(plan_id)
        if not plan:
            return None
        plan.status = status
        await self.db.flush()
        await self.db.refresh(plan)
        logger.info(f"[TEST PLAN REPO] Plan {plan_id} status → {status}")
        return plan

    async def set_ai_draft_fields(
        self,
        plan_id: str,
        fields: dict,
        generated_at,
    ) -> Optional[TestPlan]:
        plan = await self.get_by_id(plan_id)
        if not plan:
            return None

        for k, v in fields.items():
            if hasattr(plan, k):
                setattr(plan, k, v)

        plan.ai_draft_generated_at = generated_at
        plan.status = "ai_proposed"

        await self.db.flush()
        await self.db.refresh(plan)
        logger.info(f"[TEST PLAN REPO] AI draft fields set for plan {plan_id}")
        return plan

    async def approve(self, plan_id: str, approved_at) -> Optional[TestPlan]:
        plan = await self.get_by_id(plan_id)
        if not plan:
            return None
        plan.status = "approved"
        plan.approved_at = approved_at
        await self.db.flush()
        await self.db.refresh(plan)
        logger.info(f"[TEST PLAN REPO] Plan {plan_id} approved")
        return plan

    # ============================================================
    # DELETE
    # ============================================================

    async def delete(self, plan_id: str) -> bool:
        plan = await self.get_by_id(plan_id)
        if not plan:
            return False
        await self.db.delete(plan)
        await self.db.flush()
        logger.info(f"[TEST PLAN REPO] Deleted plan {plan_id}")
        return True

    async def delete_by_project(self, project_id: str) -> int:
        """Supprime tous les Test Plans d'un projet."""
        result = await self.db.execute(
            select(TestPlan).where(TestPlan.project_id == project_id)
        )
        plans = result.scalars().all()
        count = len(plans)
        for plan in plans:
            await self.db.delete(plan)
        await self.db.flush()
        logger.info(f"[TEST PLAN REPO] Deleted {count} plans for project {project_id}")
        return count

    # ============================================================
    # STATISTICS
    # ============================================================

    async def get_summary_by_project(self, project_id: str) -> dict:
        result = await self.db.execute(
            select(TestPlan.status, func.count(TestPlan.id))
            .where(TestPlan.project_id == project_id)
            .group_by(TestPlan.status)
        )
        by_status = {row[0]: row[1] for row in result.all()}

        total = sum(by_status.values())
        return {
            "total": total,
            "by_status": by_status,
            "approved": by_status.get("approved", 0) + by_status.get("active", 0),
            "pending": by_status.get("draft", 0) + by_status.get("ai_proposed", 0),
        }

    # ============================================================
    # HELPERS
    # ============================================================

    async def _validate_project(self, project_id: str) -> None:
        result = await self.db.execute(
            select(JiraProject).where(JiraProject.id == project_id)
        )
        if not result.scalar_one_or_none():
            raise ValueError(f"Project {project_id} not found")

    async def _validate_accepted_risks(
        self,
        project_id: str,
        sprint_ids: Optional[List[str]] = None,
        epic_keys: Optional[List[str]] = None,
    ) -> None:
        """Vérifie que toutes les US ciblées ont des risques acceptés."""
        
        # Récupère les US du projet avec filtres
        us_query = select(UserStory.id).where(UserStory.project_id == project_id)

        if sprint_ids:
            us_query = us_query.where(UserStory.sprint.in_(sprint_ids))
        if epic_keys:
            us_query = us_query.where(
                or_(
                    UserStory.epic_key.in_(epic_keys),
                    UserStory.epic_name.in_(epic_keys)
                )
            )

        us_result = await self.db.execute(us_query)
        us_ids = [row[0] for row in us_result.all()]

        if not us_ids:
            return  # Pas d'US, rien à valider

        # Vérifie que chaque US a au moins un risque accepté
        risks_query = (
            select(Risk.user_story_id)
            .where(
                Risk.user_story_id.in_(us_ids),
                Risk.is_accepted == True
            )
            .distinct()
        )
        risks_result = await self.db.execute(risks_query)
        us_with_accepted_risks = {row[0] for row in risks_result.all()}

        unaccepted = set(us_ids) - us_with_accepted_risks
        if unaccepted:
            raise ValueError(
                f"Cannot create Test Plan: {len(unaccepted)} User Stories "
                f"have no accepted risks. Accept risks first."
            )

    @staticmethod
    def compute_pagination(total: int, page: int, page_size: int) -> dict:
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, math.ceil(total / page_size)),
        }