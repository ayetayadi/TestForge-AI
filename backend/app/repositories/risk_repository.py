"""Risk repository for database operations ()."""

import logging
from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk import Risk
from app.models.user_story import UserStory
from app.models.test_plan import TestPlan
from app.models.jira_project import JiraProject
from app.schemas.risk_schema import RiskCreate, RiskUpdate, RiskFilters

logger = logging.getLogger(__name__)


class RiskRepository:
    """Repository for Risk entity following ."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ============================================================
    # CREATE
    # ============================================================
    
    async def create(self, data: RiskCreate) -> Risk:
        """Create a new risk (automatically computes risk_score and level)."""
        await self._validate_foreign_keys(data.project_id, data.test_plan_id, data.user_story_id)

        risk_score = data.compute_risk_score()
        level = data.compute_level()

        risk = Risk(
            id=str(uuid4()),
            project_id=data.project_id,
            test_plan_id=data.test_plan_id,
            user_story_id=data.user_story_id,
            description=data.description,
            mitigation=data.mitigation,
            reasoning=data.reasoning,
            probability=data.probability,
            impact=data.impact,
            risk_score=risk_score,
            level=level,
            is_ai_generated=data.is_ai_generated,
            is_accepted=data.is_accepted,
            source=data.source,
            source_version_id=data.source_version_id,
            source_story_text=data.source_story_text,
            source_acceptance_criteria=data.source_acceptance_criteria,
        )
        
        self.db.add(risk)
        await self.db.flush()
        await self.db.refresh(risk)
        
        logger.info(f"[RISK REPO] Created risk {risk.id} with score={risk_score} level={level}")
        return risk
    
    async def create_batch(self, items: List[RiskCreate]) -> Tuple[List[Risk], List[dict]]:
        """Create multiple risks in batch."""
        created = []
        failed = []
        
        for idx, data in enumerate(items):
            try:
                risk = await self.create(data)
                created.append(risk)
            except Exception as e:
                logger.error(f"[RISK REPO] Batch create failed at index {idx}: {e}")
                failed.append({"index": idx, "error": str(e)})
        
        await self.db.commit()
        return created, failed
    
    # ============================================================
    # READ
    # ============================================================
    
    async def get_by_id(self, risk_id: str) -> Optional[Risk]:
        """Get a single risk by ID."""
        stmt = select(Risk).options(selectinload(Risk.user_story)).where(Risk.id == risk_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_test_plan(
        self,
        test_plan_id: str,
        page: int = 1,
        page_size: int = 50,
        filters: Optional[RiskFilters] = None,
    ) -> Tuple[List[Risk], int]:
        """Get paginated risks for a test plan with optional filters."""
        stmt = select(Risk).options(selectinload(Risk.user_story)).where(Risk.test_plan_id == test_plan_id)
        
        if filters:
            stmt = self._apply_filters(stmt, filters)
        
        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.db.scalar(count_stmt)
        
        # Pagination
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        stmt = stmt.order_by(Risk.risk_score.desc())  # Highest risks first
        
        result = await self.db.execute(stmt)
        items = result.scalars().all()
        
        return items, total or 0
    
    async def get_by_project(
        self,
        project_id: str,
        filters: Optional[RiskFilters] = None,
    ) -> List[Risk]:
        """Get all risks for a project, ordered by score desc."""
        stmt = select(Risk).options(selectinload(Risk.user_story)).where(Risk.project_id == project_id)
        if filters:
            stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(Risk.risk_score.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_user_story(self, user_story_id: str) -> List[Risk]:
        """Get all risks for a specific user story."""
        stmt = select(Risk).options(selectinload(Risk.user_story)).where(Risk.user_story_id == user_story_id)
        stmt = stmt.order_by(Risk.risk_score.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_all(self, filters: Optional[RiskFilters] = None) -> List[Risk]:
        """Get all risks across all projects, ordered by score desc."""
        stmt = select(Risk).options(selectinload(Risk.user_story))
        if filters:
            stmt = self._apply_filters(stmt, filters)
        stmt = stmt.order_by(Risk.risk_score.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_high_priority_risks(
        self,
        test_plan_id: str,
        min_score: float = 2.5
    ) -> List[Risk]:
        """Get risks above threshold (ISTQB: Haute or Critique)."""
        stmt = (
            select(Risk)
            .options(selectinload(Risk.user_story))
            .where(Risk.test_plan_id == test_plan_id)
            .where(Risk.risk_score >= min_score)
            .order_by(Risk.risk_score.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    # ============================================================
    # UPDATE
    # ============================================================
    
    async def set_test_plan_id(self, risk_id: str, test_plan_id: str) -> None:
        risk = await self.get_by_id(risk_id)
        if risk:
            risk.test_plan_id = test_plan_id
            await self.db.flush()

    async def update(self, risk_id: str, data: RiskUpdate) -> Optional[Risk]:
        """Update a risk and recompute risk_score and level if P or I changed."""
        risk = await self.get_by_id(risk_id)
        if not risk:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        
        # Track if P or I changed (needs recomputation)
        p_i_changed = "probability" in update_data or "impact" in update_data
        
        # Apply updates
        for field, value in update_data.items():
            setattr(risk, field, value)
        
        # Recompute risk_score and level if needed
        if p_i_changed:
            risk.risk_score = round(risk.probability * risk.impact, 2)
            risk.level = self._compute_level(risk.risk_score)
            logger.info(f"[RISK REPO] Recomputed risk {risk_id}: score={risk.risk_score} level={risk.level}")
        
        await self.db.flush()
        await self.db.refresh(risk)
        
        return risk
    
    async def accept_risk(self, risk_id: str, accepted: bool) -> Optional[Risk]:
        """Accept or reject a risk (ISTQB: validation par le testeur)."""
        risk = await self.get_by_id(risk_id)
        if not risk:
            return None
        
        risk.is_accepted = accepted
        await self.db.flush()
        await self.db.refresh(risk)
        
        logger.info(f"[RISK REPO] Risk {risk_id} accepted={accepted}")
        return risk
    
    # ============================================================
    # DELETE
    # ============================================================
    
    async def delete(self, risk_id: str) -> bool:
        """Delete a risk by ID."""
        risk = await self.get_by_id(risk_id)
        if not risk:
            return False
        
        await self.db.delete(risk)
        await self.db.flush()
        
        logger.info(f"[RISK REPO] Deleted risk {risk_id}")
        return True
    
    async def delete_by_test_plan(self, test_plan_id: str) -> int:
        """Delete all risks for a test plan (cascade handled by DB)."""
        stmt = select(Risk).where(Risk.test_plan_id == test_plan_id)
        result = await self.db.execute(stmt)
        risks = result.scalars().all()
        
        count = len(risks)
        for risk in risks:
            await self.db.delete(risk)
        
        await self.db.flush()
        logger.info(f"[RISK REPO] Deleted {count} risks for test plan {test_plan_id}")
        return count
    
    # ============================================================
    # STATISTICS
    # ============================================================
    
    async def get_risk_summary(self, test_plan_id: str) -> dict:
        """Get risk distribution summary for a test plan."""
        stmt = select(Risk).where(Risk.test_plan_id == test_plan_id)
        result = await self.db.execute(stmt)
        return self._build_summary(result.scalars().all())

    async def get_risk_summary_by_project(self, project_id: str) -> dict:
        """Get risk distribution summary for a project."""
        stmt = select(Risk).where(Risk.project_id == project_id)
        result = await self.db.execute(stmt)
        return self._build_summary(result.scalars().all())

    def _build_summary(self, risks) -> dict:
        summary = {
            "total": len(risks),
            "by_level": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "avg_score": 0.0,
            "accepted_count": 0,
            "rejected_count": 0,
            "pending_count": 0,
        }
        total_score = 0.0
        for risk in risks:
            summary["by_level"][risk.level] = summary["by_level"].get(risk.level, 0) + 1
            total_score += risk.risk_score
            if risk.is_accepted is True:
                summary["accepted_count"] += 1
            elif risk.is_accepted is False:
                summary["rejected_count"] += 1
            else:
                summary["pending_count"] += 1
        if risks:
            summary["avg_score"] = round(total_score / len(risks), 2)
        return summary
    
    # ============================================================
    # PRIVATE HELPERS
    # ============================================================
    
    async def _validate_foreign_keys(
        self,
        project_id: str,
        test_plan_id: Optional[str],
        user_story_id: Optional[str],
    ) -> None:
        """Validate that referenced entities exist."""
        result = await self.db.execute(select(JiraProject).where(JiraProject.id == project_id))
        if not result.scalar_one_or_none():
            raise ValueError(f"Project {project_id} not found")

        if test_plan_id:
            result = await self.db.execute(select(TestPlan).where(TestPlan.id == test_plan_id))
            if not result.scalar_one_or_none():
                raise ValueError(f"TestPlan {test_plan_id} not found")

        if user_story_id:
            result = await self.db.execute(select(UserStory).where(UserStory.id == user_story_id))
            if not result.scalar_one_or_none():
                raise ValueError(f"UserStory {user_story_id} not found")
    
    def _apply_filters(self, stmt, filters: RiskFilters):
        """Apply filters to a select statement."""
        if filters.user_story_id:
            stmt = stmt.where(Risk.user_story_id == filters.user_story_id)
        if filters.level:
            stmt = stmt.where(Risk.level == filters.level)
        if filters.is_accepted is not None:
            stmt = stmt.where(Risk.is_accepted == filters.is_accepted)
        if filters.is_ai_generated is not None:
            stmt = stmt.where(Risk.is_ai_generated == filters.is_ai_generated)
        if filters.min_risk_score is not None:
            stmt = stmt.where(Risk.risk_score >= filters.min_risk_score)
        if filters.max_risk_score is not None:
            stmt = stmt.where(Risk.risk_score <= filters.max_risk_score)
        return stmt
    
    @staticmethod
    def _compute_level(risk_score: float) -> str:
        """ISTQB classification based on risk score."""
        if risk_score >= 4.0:
            return "critical"
        if risk_score >= 2.5:
            return "high"
        if risk_score >= 1.0:
            return "medium"
        return "low"