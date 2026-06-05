"""Risk service for business logic - LLM-Based Risk Analysis."""

from datetime import datetime
import logging
from typing import List, Optional, Dict, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.risk_repository import RiskRepository
from app.models.user_story_version import UserStoryVersion
from app.models.enums import StoryDecision
from app.models.risk import Risk as RiskModel
from app.schemas.risk_schema import (
    RiskCreate,
    RiskUpdate,
    RiskResponse,
    RiskFilters,
    RiskListResponse,
    RiskBatchResponse,
)
from app.ai_workflows.risk_analysis.pipeline import (
    RiskAnalysisPipeline,
    get_pipeline,
    analyse_stories_batch,
)

logger = logging.getLogger(__name__)


class RiskService:
    """Service for risk management following Risk Based Testing (ISTQB)."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = RiskRepository(db)
    
    # ============================================================
    # LLM-POWERED RISK ANALYSIS
    # ============================================================
    async def analyze_user_story(
        self,
        story: str,
        acceptance_criteria: List[str],
        user_story_id: str,
        issue_key: str = "?",
        test_plan_id: Optional[str] = None,
    ) -> RiskResponse:
        """
        Analyze a User Story with LLM for risk assessment.
        
        Pipeline (aligned with Risk Based Testing document):
          1. LLM analyzes story + ACs
          2. Returns P (1-5), I (1-5), description, mitigation, reasoning
          3. Calculates Score = P × I
          4. Classifies level: Critical (20+) / High (12-19) / Medium (6-11) / Low (1-5)
          5. Recommends test depth
        """
        pipeline = get_pipeline()
        
        result = await pipeline.run(
            story=story,
            acceptance_criteria=acceptance_criteria,
            issue_key=issue_key,
            user_story_id=user_story_id,
            test_plan_id=test_plan_id,
        )
        
        if result.get("workflow_status") == "error":
            logger.error(f"Risk analysis failed: {result.get('error')}")
            raise ValueError(f"Risk analysis failed: {result.get('error')}")
        
        risk_create = RiskCreate(
            user_story_id=user_story_id,
            test_plan_id=test_plan_id,
            description=result["description"],
            mitigation=result.get("mitigation", ""),
            reasoning=result.get("reasoning", ""),
            probability=result["probability"],          # 1-5
            impact=result["impact"],                    # 1-5
            probability_factors=result.get("probability_factors"),
            impact_factors=result.get("impact_factors"),
            probability_reasoning=result.get("probability_reasoning"),
            impact_reasoning=result.get("impact_reasoning"),
            test_depth=result.get("test_depth", "standard"),
            is_ai_generated=True,
            is_accepted=None,
            source="llm",
            source_story_text=story,
            source_acceptance_criteria=acceptance_criteria,
        )
    
        risk = await self.repository.create(risk_create)
        await self.db.commit()
    
        logger.info(
            f"[RISK SERVICE] Analysis complete for {issue_key}: "
            f"P={risk.probability} I={risk.impact} Score={risk.risk_score} "
            f"Level={risk.level} TestDepth={risk.test_depth}"
        )
        
        return RiskResponse.model_validate(risk)

    async def analyze_user_stories_batch(
        self,
        stories_data: List[Dict[str, Any]],
        test_plan_id: Optional[str] = None,
        concurrency: int = 2,
    ) -> RiskBatchResponse:
        """
        Analyze multiple User Stories in batch with LLM.
        
        Args:
            stories_data: List of dicts with keys:
                - story (str): The user story text
                - acceptance_criteria (List[str]): ACs
                - user_story_id (str): DB ID
                - issue_key (str): Jira key
            test_plan_id: Optional test plan to link risks to
            concurrency: Max parallel LLM calls (keep low to avoid rate limits)
        """
        pipeline = get_pipeline()
        
        # Run batch analysis via pipeline
        ai_results = await analyse_stories_batch(
            pipeline=pipeline,
            stories=stories_data,
            test_plan_id=test_plan_id,
            concurrency=concurrency,
        )
        
        # Transform each result into a persisted risk
        created = []
        failed = []
        
        for idx, result in enumerate(ai_results):
            if result.get("workflow_status") == "error":
                failed.append({
                    "index": idx,
                    "error": result.get("error", "Unknown error"),
                    "issue_key": result.get("issue_key", "?"),
                })
                continue
            
            try:
                risk_create = RiskCreate(
                    user_story_id=result.get("user_story_id"),
                    test_plan_id=test_plan_id,
                    description=result["description"],
                    mitigation=result.get("mitigation", ""),
                    reasoning=result.get("reasoning", ""),
                    probability=result["probability"],
                    impact=result["impact"],
                    probability_factors=result.get("probability_factors"),
                    impact_factors=result.get("impact_factors"),
                    probability_reasoning=result.get("probability_reasoning"),
                    impact_reasoning=result.get("impact_reasoning"),
                    test_depth=result.get("test_depth", "standard"),
                    is_ai_generated=True,
                    is_accepted=None,
                    source="llm",
                    source_story_text=result.get("source_story_text", ""),
                    source_acceptance_criteria=result.get("source_acceptance_criteria", []),
                )
                
                risk = await self.repository.create(risk_create)
                created.append(risk)
                
            except Exception as e:
                logger.error(f"Failed to persist risk for {result.get('issue_key')}: {e}")
                failed.append({
                    "index": idx,
                    "error": str(e),
                    "issue_key": result.get("issue_key", "?"),
                })
        
        await self.db.commit()
        
        return RiskBatchResponse(
            created=[RiskResponse.model_validate(r) for r in created],
            failed=failed,
            total_success=len(created),
            total_failed=len(failed),
        )
    
    async def analyze_risks_for_project(
        self,
        project_id: str,
        sprint: Optional[str] = None,
        epic_key: Optional[str] = None,
        use_approved_version_only: bool = False,
        base_data: Optional[RiskCreate] = None,
    ) -> RiskBatchResponse:
        """
        Create risks for all UserStories in a project/sprint/epic.
        Uses repository for batch creation.
        """
        created, failed = await self.repository.create_for_stories(
            project_id=project_id,
            sprint=sprint,
            epic_key=epic_key,
            use_approved_version_only=use_approved_version_only,
            base_data=base_data,
        )
        
        await self.db.commit()
        
        return RiskBatchResponse(
            created=[RiskResponse.model_validate(r) for r in created],
            failed=failed,
            total_success=len(created),
            total_failed=len(failed),
        )
    
    # ============================================================
    # MANUAL RISK CREATION (without AI)
    # ============================================================
    
    async def create_risk_manual(self, data: RiskCreate) -> RiskResponse:
        """Manual risk creation (without AI, is_ai_generated=False)."""
        data.is_ai_generated = False
        risk = await self.repository.create(data)
        await self.db.commit()
        return RiskResponse.model_validate(risk)
    
    # ============================================================
    # READ OPERATIONS
    # ============================================================
    
    async def get_risk(self, risk_id: str) -> Optional[RiskResponse]:
        """Get a single risk by ID."""
        risk = await self.repository.get_by_id(risk_id)
        return RiskResponse.model_validate(risk) if risk else None
    
    async def _compute_eligibility(self, risks: list) -> dict:
        """
        Batch-compute eligible_for_reanalysis for a list of Risk ORM objects.

        A story is eligible when, since its last risk was created:
          - Condition A: it was re-synced from Jira (jira_updated_at or updated_at > risk.created_at)
          - Condition B: a new approved refinement version was created (version.started_at > risk.created_at)

        Returns a dict {risk_id: bool}.
        """
        if not risks:
            return {}

        story_ids = [r.user_story_id for r in risks if r.user_story_id]

        # Batch: latest approved version date per story
        approved_map: dict[str, datetime] = {}
        if story_ids:
            stmt = (
                select(UserStoryVersion.user_story_id, func.max(UserStoryVersion.started_at))
                .where(
                    UserStoryVersion.user_story_id.in_(story_ids),
                    UserStoryVersion.decision_status == StoryDecision.APPROVED,
                )
                .group_by(UserStoryVersion.user_story_id)
            )
            result = await self.db.execute(stmt)
            approved_map = {row[0]: row[1] for row in result.all()}

        from datetime import timezone as _tz

        def _as_aware(dt):
            if dt is None:
                return None
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=_tz.utc)

        eligibility: dict[str, bool] = {}
        for risk in risks:
            story = risk.user_story
            if not story:
                eligibility[risk.id] = False
                continue
            jira_ts = _as_aware(story.jira_updated_at or story.updated_at)
            risk_created = _as_aware(risk.created_at)
            cond_a = jira_ts is not None and risk_created is not None and jira_ts > risk_created
            latest_approved = _as_aware(approved_map.get(risk.user_story_id))
            cond_b = latest_approved is not None and risk_created is not None and latest_approved > risk_created
            eligibility[risk.id] = bool(cond_a or cond_b)

        return eligibility

    async def get_all_risks(
        self,
        project_id: Optional[str] = None,
        sprint: Optional[str] = None,
        epic_key: Optional[str] = None,
        level: Optional[str] = None,
        is_accepted: Optional[bool] = None,
        source: Optional[str] = None,
        project_ids=None,
    ) -> List[RiskResponse]:
        """Get all risks with optional filters (no pagination)."""
        items, _ = await self.repository.get_all(
            project_id=project_id,
            sprint=sprint,
            epic_key=epic_key,
            level=level,
            is_accepted=is_accepted,
            source=source,
            project_ids=project_ids,
        )
        eligibility = await self._compute_eligibility(items)
        responses = []
        for item in items:
            resp = RiskResponse.model_validate(item)
            resp.eligible_for_reanalysis = eligibility.get(item.id, False)
            responses.append(resp)
        return responses

    async def list_risks(
        self,
        project_id: Optional[str] = None,
        sprint: Optional[str] = None,
        epic_key: Optional[str] = None,
        user_story_id: Optional[str] = None,
        level: Optional[str] = None,
        is_accepted: Optional[bool] = None,
        source: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> RiskListResponse:
        """Get paginated list of risks with optional filters."""
        items, total = await self.repository.get_all(
            project_id=project_id,
            sprint=sprint,
            epic_key=epic_key,
            user_story_id=user_story_id,
            level=level,
            is_accepted=is_accepted,
            source=source,
            page=page,
            page_size=page_size,
        )
        
        return RiskListResponse(
            items=[RiskResponse.model_validate(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size if total > 0 else 0,
        )
    
    async def get_risks_by_project(
        self,
        project_id: str,
        level: Optional[str] = None,
        is_accepted: Optional[bool] = None,
        is_ai_generated: Optional[bool] = None,
    ) -> List[RiskResponse]:
        """Get all risks for a project with optional filters."""
        filters = RiskFilters(
            level=level,
            is_accepted=is_accepted,
            is_ai_generated=is_ai_generated,
        )
        risks = await self.repository.get_by_project(project_id, filters)
        eligibility = await self._compute_eligibility(risks)
        responses = []
        for r in risks:
            resp = RiskResponse.model_validate(r)
            resp.eligible_for_reanalysis = eligibility.get(r.id, False)
            responses.append(resp)
        return responses
    
    async def get_risks_by_sprint(
        self,
        project_id: str,
        sprint: str,
        level: Optional[str] = None,
        is_accepted: Optional[bool] = None,
    ) -> List[RiskResponse]:
        """Get all risks for a sprint."""
        items, _ = await self.repository.get_all(
            project_id=project_id,
            sprint=sprint,
            level=level,
            is_accepted=is_accepted,
        )
        return [RiskResponse.model_validate(r) for r in items]
    
    async def get_risks_by_epic(
        self,
        project_id: str,
        epic_key: str,
        level: Optional[str] = None,
    ) -> List[RiskResponse]:
        """Get all risks for an epic."""
        items, _ = await self.repository.get_all(
            project_id=project_id,
            epic_key=epic_key,
            level=level,
        )
        return [RiskResponse.model_validate(r) for r in items]

    async def get_risks_by_user_story(self, user_story_id: str) -> List[RiskResponse]:
        """Get all risks for a specific user story."""
        risks = await self.repository.get_by_user_story(user_story_id)
        return [RiskResponse.model_validate(r) for r in risks]

    async def get_risk_summary_by_project(self, project_id: str) -> dict:
        """Get risk distribution summary for a project."""
        return await self.repository.get_risk_summary_by_project(project_id)
    
    async def get_risk_summary_by_sprint(self, project_id: str, sprint: str) -> dict:
        """Get risk distribution summary for a sprint."""
        return await self.repository.get_risk_summary_by_sprint(project_id, sprint)

    async def get_risk_summary_by_epic(self, project_id: str, epic_key: str) -> dict:
        """Get risk distribution summary for an epic."""
        return await self.repository.get_risk_summary_by_epic(project_id, epic_key)

    async def get_high_priority_risks(
        self, 
        project_id: Optional[str] = None,
        min_score: int = 12  # Document original: High ≥ 12
    ) -> List[RiskResponse]:
        """Get high or critical risks (High ≥ 12, Critical ≥ 20)."""
        risks = await self.repository.get_high_priority_risks(project_id, min_score)
        return [RiskResponse.model_validate(r) for r in risks]
    
    async def get_critical_risks(
        self,
        project_id: Optional[str] = None,
    ) -> List[RiskResponse]:
        """Get critical risks only (score ≥ 20)."""
        risks = await self.repository.get_critical_risks(project_id)
        return [RiskResponse.model_validate(r) for r in risks]

    # ============================================================
    # HUMAN CORRECTION (QA Lead overrides LLM)
    # ============================================================
    
    async def human_correct_risk(
        self,
        risk_id: str,
        probability: int,
        impact: int,
        comment: Optional[str] = None,
    ) -> Optional[RiskResponse]:
        """
        Human correction of an LLM-generated risk.
        QA lead can override P and I values.
        """
        risk = await self.repository.get_by_id(risk_id)
        if not risk:
            return None
        
        # Apply human correction
        risk.probability = max(1, min(5, probability))
        risk.impact = max(1, min(5, impact))
        risk.risk_score = risk.probability * risk.impact
        
        # Reclassify (document original thresholds)
        if risk.risk_score >= 20:
            risk.level = "critical"
        elif risk.risk_score >= 12:
            risk.level = "high"
        elif risk.risk_score >= 6:
            risk.level = "medium"
        else:
            risk.level = "low"
        
        # Update test recommendations
        risk.test_depth = self._get_test_depth(risk.level)
        
        risk.is_accepted = True
        risk.source = "human_modified"
        
        # Store correction metadata
        risk.correction_comment = comment
        risk.corrected_at = datetime.utcnow()
        
        await self.db.flush()
        await self.db.refresh(risk)
        await self.db.commit()
        
        logger.info(
            f"[RISK SERVICE] Human correction for {risk_id}: "
            f"P={risk.probability} I={risk.impact} Score={risk.risk_score} Level={risk.level}"
        )
        
        return RiskResponse.model_validate(risk)
    
    # ============================================================
    # UPDATE
    # ============================================================
    
    async def update_risk(self, risk_id: str, data: RiskUpdate) -> Optional[RiskResponse]:
        """Update a risk (recomputes score if P or I changed)."""
        risk = await self.repository.update(risk_id, data)
        if not risk:
            return None
        await self.db.commit()
        return RiskResponse.model_validate(risk)
    
    async def accept_risk(self, risk_id: str, accepted: bool) -> Optional[RiskResponse]:
        """Accept or reject a risk analysis."""
        risk = await self.repository.accept_risk(risk_id, accepted)
        if not risk:
            return None
        await self.db.commit()
        return RiskResponse.model_validate(risk)
    
    async def propose_mitigation(self, risk_id: str, mitigation: str) -> Optional[RiskResponse]:
        """Update mitigation strategy for a risk."""
        return await self.update_risk(risk_id, RiskUpdate(mitigation=mitigation))
    
    async def reanalyze_risk(
        self, 
        risk_id: str, 
        story: str,
        acceptance_criteria: List[str],
    ) -> Optional[RiskResponse]:
        """Re-analyze an existing risk with LLM."""
        risk = await self.repository.get_by_id(risk_id)
        if not risk:
            return None
        
        pipeline = get_pipeline()
        result = await pipeline.run(
            story=story,
            acceptance_criteria=acceptance_criteria,
            issue_key=risk.user_story_key or "?",
            user_story_id=risk.user_story_id,
            test_plan_id=risk.test_plan_id,
        )
        
        if result.get("workflow_status") == "error":
            raise ValueError(f"Re-analysis failed: {result.get('error')}")
        
        # Update risk with new LLM results
        risk.probability = result["probability"]
        risk.impact = result["impact"]
        risk.risk_score = result["risk_score"]
        risk.level = result["level"]
        risk.description = result["description"]
        risk.mitigation = result.get("mitigation", "")
        risk.reasoning = result.get("reasoning", "")
        risk.probability_factors = result.get("probability_factors")
        risk.impact_factors = result.get("impact_factors")
        risk.probability_reasoning = result.get("probability_reasoning")
        risk.impact_reasoning = result.get("impact_reasoning")
        risk.test_depth = result.get("test_depth", risk.test_depth)
        risk.is_ai_generated = True
        risk.is_accepted = None
        
        await self.db.flush()
        await self.db.refresh(risk)
        await self.db.commit()
        
        logger.info(f"[RISK SERVICE] Re-analysis complete for {risk_id}")
        
        return RiskResponse.model_validate(risk)

    # ============================================================
    # DELETE
    # ============================================================
    
    async def delete_risk(self, risk_id: str) -> bool:
        """Delete a single risk."""
        deleted = await self.repository.delete(risk_id)
        await self.db.commit()
        return deleted
    
    async def delete_project_risks(self, project_id: str) -> int:
        """Delete all risks for a project."""
        count = await self.repository.delete_by_project(project_id)
        await self.db.commit()
        return count
    
    # ============================================================
    # PRIVATE HELPERS
    # ============================================================
    
    @staticmethod
    def _get_test_depth(level: str) -> str:
        """Get test depth based on risk level."""
        depth_map = {
            "critical": "comprehensive",
            "high": "thorough",
            "medium": "standard",
            "low": "smoke"
        }
        return depth_map.get(level, "standard")
    