"""Risk repository for database operations."""

import logging
from typing import List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.risk import Risk
from app.models.user_story import UserStory
from app.models.jira_project import JiraProject
from app.schemas.risk_schema import RiskCreate, RiskUpdate, RiskFilters
from app.models.user_story_version import UserStoryVersion

logger = logging.getLogger(__name__)


class RiskRepository:
    """Repository for Risk entity."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ============================================================
    # CREATE
    # ============================================================
    
    async def create(self, data: RiskCreate) -> Risk:
        """Create a single risk."""
        await self._validate_foreign_keys(data.user_story_id)

        risk_score = data.compute_risk_score()
        level = data.compute_level()
        test_depth = self._get_test_depth(level)

        risk = Risk(
            id=str(uuid4()),
            user_story_id=data.user_story_id,
            test_plan_id=data.test_plan_id,
            description=data.description,
            mitigation=data.mitigation,
            reasoning=data.reasoning,
            probability=data.probability,
            probability_factors=data.probability_factors,
            probability_reasoning=data.probability_reasoning,
            impact=data.impact,
            impact_factors=data.impact_factors,
            impact_reasoning=data.impact_reasoning,
            risk_score=risk_score,
            level=level,
            test_depth=test_depth,
            test_techniques=data.test_techniques or self._get_default_techniques(level),
            effort_allocation=data.effort_allocation or self._get_effort_allocation(level),
            is_ai_generated=data.is_ai_generated,
            is_accepted=data.is_accepted,
            source=data.source,
            source_story_text=data.source_story_text,
            source_acceptance_criteria=data.source_acceptance_criteria,
        )
        
        self.db.add(risk)
        await self.db.flush()
        await self.db.refresh(risk)
        
        logger.info(f"[RISK REPO] Created risk {risk.id} P={risk.probability} I={risk.impact} Score={risk_score} Level={level}")
        return risk
    
    async def create_for_stories(
        self,
        project_id: str,
        sprint: Optional[str] = None,
        epic_key: Optional[str] = None,
        use_approved_version_only: bool = False,
        base_data: Optional[RiskCreate] = None,
    ) -> Tuple[List[Risk], List[dict]]:
        """
        Create risks for all UserStories matching the filters.
        
        Args:
            project_id: Jira project concerned
            sprint: Filter by sprint
            epic_key: Filter by epic
            use_approved_version_only: Use only approved versions
            base_data: Base data for each risk
        """
        stmt = select(UserStory).where(UserStory.project_id == project_id)
        
        if sprint:
            stmt = stmt.where(UserStory.sprint == sprint)
        if epic_key:
            stmt = stmt.where(UserStory.epic_key == epic_key)
        
        result = await self.db.execute(stmt)
        user_stories = result.scalars().all()
        
        created = []
        failed = []
        
        for us in user_stories:
            try:
                source_text = f"{us.title}\n{us.description or ''}"
                version_id = None
                ac_criteria = us.acceptance_criteria or []
                source = "original"
                
                if use_approved_version_only:
                    approved = await self._get_last_approved_version(us.id)
                    if not approved:
                        continue
                    source_text = approved.improved_story
                    version_id = approved.id
                    ac_criteria = approved.generated_acceptance_criteria or []
                    source = "approved_version"
                
                risk_data = RiskCreate(
                    user_story_id=us.id,
                    source_story_text=source_text,
                    source_acceptance_criteria=ac_criteria,
                    source=source,
                    **(base_data.model_dump(exclude={'user_story_id'}) if base_data else {})
                )
                
                risk = await self.create(risk_data)
                created.append(risk)
                
            except Exception as e:
                logger.error(f"[RISK REPO] Failed for {us.issue_key}: {e}")
                failed.append({"issue_key": us.issue_key, "error": str(e)})
        
        await self.db.commit()
        return created, failed

    async def create_batch(self, items: List[RiskCreate]) -> Tuple[List[Risk], List[dict]]:
        """Create multiple risks from a list."""
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
    
    async def get_by_project(
        self,
        project_id: str,
        filters: Optional[RiskFilters] = None,
    ) -> List[Risk]:
        """Get all risks for a project via UserStory."""
        stmt = (
            select(Risk)
            .join(UserStory, Risk.user_story_id == UserStory.id)
            .options(selectinload(Risk.user_story))
            .where(UserStory.project_id == project_id)
            .order_by(Risk.risk_score.desc())
        )
    
        if filters:
            stmt = self._apply_filters(stmt, filters)
    
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_user_story(self, user_story_id: str) -> List[Risk]:
        """Get all risks for a specific user story."""
        stmt = (
            select(Risk)
            .options(selectinload(Risk.user_story))
            .where(Risk.user_story_id == user_story_id)
            .order_by(Risk.risk_score.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_all(
        self,
        project_id: Optional[str] = None,
        sprint: Optional[str] = None,
        epic_key: Optional[str] = None,
        user_story_id: Optional[str] = None,
        level: Optional[str] = None,
        is_accepted: Optional[bool] = None,
        source: Optional[str] = None,
    ) -> Tuple[List[Risk], int]:
        """
        Get all risks with optional filters.
        
        Examples:
        - get_all() → All risks
        - get_all(project_id="proj-1") → Project risks
        - get_all(project_id="proj-1", sprint="Sprint 4") → Sprint risks
        - get_all(project_id="proj-1", epic_key="SCRUM-12") → Epic risks
        - get_all(level="critical") → Critical risks across all projects
        - get_all(source="approved_version") → Risks from approved versions
        """
        stmt = select(Risk).options(selectinload(Risk.user_story))
        
        # JOIN only if filtering by project/sprint/epic
        if project_id or sprint or epic_key:
            stmt = stmt.join(UserStory, Risk.user_story_id == UserStory.id)
            
            if project_id:
                stmt = stmt.where(UserStory.project_id == project_id)
            if sprint:
                stmt = stmt.where(UserStory.sprint == sprint)
            if epic_key:
                stmt = stmt.where(UserStory.epic_key == epic_key)
        
        # Direct Risk filters
        if user_story_id:
            stmt = stmt.where(Risk.user_story_id == user_story_id)
        if level:
            stmt = stmt.where(Risk.level == level)
        if is_accepted is not None:
            stmt = stmt.where(Risk.is_accepted == is_accepted)
        if source:
            stmt = stmt.where(Risk.source == source)
        
        # Pagination
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.db.scalar(count_stmt)
        
        stmt = stmt.order_by(Risk.risk_score.desc())
        
        result = await self.db.execute(stmt)
        return result.scalars().all(), total or 0

    async def get_high_priority_risks(
        self,
        project_id: Optional[str] = None,
        min_score: int = 12  # Document original: High ≥ 12
    ) -> List[Risk]:
        """Get risks above threshold for a project."""
        stmt = (
            select(Risk)
            .options(selectinload(Risk.user_story))
            .where(Risk.risk_score >= min_score)
        )
        
        if project_id:
            stmt = stmt.join(UserStory, Risk.user_story_id == UserStory.id)
            stmt = stmt.where(UserStory.project_id == project_id)
        
        stmt = stmt.order_by(Risk.risk_score.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_critical_risks(self, project_id: Optional[str] = None) -> List[Risk]:
        """Get critical risks (score ≥ 20) for a project."""
        return await self.get_high_priority_risks(
            project_id=project_id, 
            min_score=20  # Critical threshold per original document
        )
    
    # ============================================================
    # UPDATE
    # ============================================================
    
    async def update(self, risk_id: str, data: RiskUpdate) -> Optional[Risk]:
        """Update a risk and recompute score/level if P or I changed."""
        risk = await self.get_by_id(risk_id)
        if not risk:
            return None
        
        update_data = data.model_dump(exclude_unset=True)
        
        p_i_changed = "probability" in update_data or "impact" in update_data
        
        for field, value in update_data.items():
            setattr(risk, field, value)
        
        if p_i_changed:
            # Recalculate score (P × I, integer 1-25)
            risk.risk_score = risk.probability * risk.impact
            
            # Reclassify level (document original thresholds)
            if risk.risk_score >= 20:
                risk.level = "critical"
            elif risk.risk_score >= 12:
                risk.level = "high"
            elif risk.risk_score >= 6:
                risk.level = "medium"
            else:
                risk.level = "low"
            
            # Update test depth accordingly
            risk.test_depth = self._get_test_depth(risk.level)
            risk.test_techniques = self._get_default_techniques(risk.level)
            risk.effort_allocation = self._get_effort_allocation(risk.level)
            
            logger.info(
                f"[RISK REPO] Recomputed risk {risk_id}: "
                f"P={risk.probability} I={risk.impact} "
                f"Score={risk.risk_score} Level={risk.level}"
            )
        
        await self.db.flush()
        await self.db.refresh(risk)
        
        return risk
    
    async def accept_risk(self, risk_id: str, accepted: bool) -> Optional[Risk]:
        """Accept or reject a risk analysis."""
        risk = await self.get_by_id(risk_id)
        if not risk:
            return None
        
        risk.accept() if accepted else risk.reject()
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
    
    async def delete_by_project(self, project_id: str) -> int:
        """Delete all risks for a project via UserStory."""
        stmt = (
            select(Risk)
            .join(UserStory, Risk.user_story_id == UserStory.id)
            .where(UserStory.project_id == project_id)
        )
        result = await self.db.execute(stmt)
        risks = result.scalars().all()
        
        count = len(risks)
        for risk in risks:
            await self.db.delete(risk)
        
        await self.db.flush()
        logger.info(f"[RISK REPO] Deleted {count} risks for project {project_id}")
        return count
    
    # ============================================================
    # STATISTICS
    # ============================================================
    
    async def get_risk_summary_by_project(self, project_id: str) -> dict:
        """Get risk distribution summary for a project."""
        stmt = (
            select(Risk)
            .join(UserStory, Risk.user_story_id == UserStory.id)
            .where(UserStory.project_id == project_id)
            .order_by(Risk.risk_score.desc())
        )
        result = await self.db.execute(stmt)
        return self._build_summary(result.scalars().all())

    async def get_risk_summary_by_sprint(self, project_id: str, sprint: str) -> dict:
        """Get risk distribution summary for a sprint."""
        stmt = (
            select(Risk)
            .join(UserStory, Risk.user_story_id == UserStory.id)
            .where(UserStory.project_id == project_id)
            .where(UserStory.sprint == sprint)
            .order_by(Risk.risk_score.desc())
        )
        result = await self.db.execute(stmt)
        return self._build_summary(result.scalars().all())

    async def get_risk_summary_by_epic(self, project_id: str, epic_key: str) -> dict:
        """Get risk distribution summary for an epic."""
        stmt = (
            select(Risk)
            .join(UserStory, Risk.user_story_id == UserStory.id)
            .where(UserStory.project_id == project_id)
            .where(UserStory.epic_key == epic_key)
            .order_by(Risk.risk_score.desc())
        )
        result = await self.db.execute(stmt)
        return self._build_summary(result.scalars().all())

    # ============================================================
    # PRIVATE HELPERS
    # ============================================================

    async def _get_last_approved_version(self, user_story_id: str) -> Optional[UserStoryVersion]:
        """Get the last approved version of a UserStory."""
        from app.models.enums import StoryDecision
        
        stmt = (
            select(UserStoryVersion)
            .where(UserStoryVersion.user_story_id == user_story_id)
            .where(UserStoryVersion.decision_status == StoryDecision.APPROVED)
            .order_by(UserStoryVersion.version_number.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
      
    def _build_summary(self, risks) -> dict:
        """Build a summary dictionary from a list of risks."""
        summary = {
            "total": len(risks),
            "by_level": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "avg_score": 0,
            "max_score": 0,
            "min_score": 25 if risks else 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "pending_count": 0,
            "effort_distribution": {
                "critical": "0%",
                "high": "0%", 
                "medium": "0%",
                "low": "0%"
            }
        }
        
        total_score = 0
        for risk in risks:
            summary["by_level"][risk.level] = summary["by_level"].get(risk.level, 0) + 1
            total_score += risk.risk_score
            
            if risk.risk_score > summary["max_score"]:
                summary["max_score"] = risk.risk_score
            if risk.risk_score < summary["min_score"]:
                summary["min_score"] = risk.risk_score
            
            if risk.is_accepted is True:
                summary["accepted_count"] += 1
            elif risk.is_accepted is False:
                summary["rejected_count"] += 1
            else:
                summary["pending_count"] += 1
        
        if risks:
            summary["avg_score"] = round(total_score / len(risks), 0)  # Integer average
        
        # Calculate effort distribution (document original: 60/25/10/5)
        critical_count = summary["by_level"]["critical"]
        high_count = summary["by_level"]["high"]
        medium_count = summary["by_level"]["medium"]
        low_count = summary["by_level"]["low"]
        
        total_weight = (critical_count * 60 + high_count * 25 + medium_count * 10 + low_count * 5)
        if total_weight > 0:
            summary["effort_distribution"]["critical"] = f"{round(critical_count * 60 / total_weight * 100, 1)}%"
            summary["effort_distribution"]["high"] = f"{round(high_count * 25 / total_weight * 100, 1)}%"
            summary["effort_distribution"]["medium"] = f"{round(medium_count * 10 / total_weight * 100, 1)}%"
            summary["effort_distribution"]["low"] = f"{round(low_count * 5 / total_weight * 100, 1)}%"
        
        return summary
    
    async def _validate_foreign_keys(self, user_story_id: Optional[str]) -> None:
        """Validate that referenced UserStory exists."""
        if user_story_id:
            result = await self.db.execute(
                select(UserStory).where(UserStory.id == user_story_id)
            )
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
        if filters.test_depth:
            stmt = stmt.where(Risk.test_depth == filters.test_depth)
        return stmt
    
    @staticmethod
    def _compute_level(risk_score: int) -> str:
        """
        ISTQB classification based on risk score.
        ALIGNED WITH ORIGINAL DOCUMENT:
        - Critical: 20-25
        - High: 12-19
        - Medium: 6-11
        - Low: 1-5
        """
        if risk_score >= 20:
            return "critical"
        if risk_score >= 12:
            return "high"
        if risk_score >= 6:
            return "medium"
        return "low"
    
    @staticmethod
    def _get_test_depth(level: str) -> str:
        """Get test depth based on risk level (document original)."""
        depth_map = {
            "critical": "comprehensive",
            "high": "thorough",
            "medium": "standard",
            "low": "smoke"
        }
        return depth_map.get(level, "standard")
    
    @staticmethod
    def _get_default_techniques(level: str) -> list:
        """Get default test techniques based on risk level (document original)."""
        techniques_map = {
            "critical": ["unit", "integration", "e2e", "performance", "security"],
            "high": ["unit", "integration", "e2e"],
            "medium": ["unit", "integration"],
            "low": ["smoke"]
        }
        return techniques_map.get(level, ["unit"])
    
    @staticmethod
    def _get_effort_allocation(level: str) -> str:
        """Get effort allocation based on risk level (document original)."""
        allocation_map = {
            "critical": "60%",
            "high": "25%",
            "medium": "10%",
            "low": "5%"
        }
        return allocation_map.get(level, "10%")