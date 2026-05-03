"""Risk service for business logic (ISTQB - Risk Control with AI Pipeline)."""

from datetime import datetime
import logging
from typing import List, Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.risk_repository import RiskRepository
from app.schemas.risk_schema import (
    RiskCreate,
    RiskUpdate,
    RiskResponse,
    RiskFilters,
    RiskListResponse,
    RiskBatchResponse,
)
from app.ai_workflows.risk_analysis import (
    get_pipeline,
    analyse_stories_batch
)
from app.ai_workflows.risk_analysis.calculator import classify_priority

logger = logging.getLogger(__name__)


class RiskService:
    """Service for risk management following ISTQB."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = RiskRepository(db)
    
    # ============================================================
    # AI-POWERED RISK ANALYSIS (ISTQB §5.2.3)
    # ============================================================
    async def analyze_user_story(
        self,
        story: str,
        acceptance_criteria: List[str],
        user_story_id: str,
        project_id: str,
    ) -> RiskResponse:
        """
        Analyse une User Story avec ML + LLM (nouveau pipeline RBT).
        
        Pipeline :
          1. ML → P (1-5), I (1-5)
          2. Calculator → Score, Priorité, Effort
          3. LLM → Description, Mitigation, Reasoning
        """
        pipeline = await get_pipeline()
        
        result = await pipeline.run(
            user_story=story,
            acceptance_criteria=acceptance_criteria,
            user_story_id=user_story_id,
        )
        
        if result.workflow_status == "error":
            logger.error(f"Risk analysis failed: {result.error}")
            raise ValueError(f"Risk analysis failed: {result.error}")
        
        risk_create = RiskCreate(
            user_story_id=user_story_id,
            description=result.description,
            mitigation=result.mitigation,
            reasoning=result.reasoning,
            probability=result.probability,
            impact=result.impact,
            is_ai_generated=True,
            is_accepted=None,
            source=result.source,                    # "ml", "llm_fallback", etc.
            source_story_text=story,
            source_acceptance_criteria=acceptance_criteria,
            ml_confidence=result.ml_confidence,      # Ajouté
        )
    
        risk = await self.repository.create(risk_create)
        await self.db.commit()
    
        logger.info(
            f"[RISK SERVICE] Analysis complete for US {user_story_id}: "
            f"P={risk.probability} I={risk.impact} score={risk.risk_score} "
            f"level={risk.level} source={risk.source}"
        )
        
        return RiskResponse.model_validate(risk)

    async def analyze_user_stories_batch(
        self,
        stories_data: List[Dict[str, Any]],
        project_id: str,  # Contexte uniquement
        concurrency: int = 2,
    ) -> RiskBatchResponse:
        """
        Analyse plusieurs User Stories en batch avec l'IA.
        """
        pipeline = await get_pipeline()
        
        # Lancer l'analyse batch via le pipeline
        ai_results = await analyse_stories_batch(
            pipeline=pipeline,
            stories=stories_data,
            concurrency=concurrency,
        )
        
        # Transformer chaque résultat en risque en base
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
                    description=result["description"],
                    mitigation=result["mitigation"],
                    reasoning=result.get("reasoning", ""),
                    probability=result["probability"],
                    impact=result["impact"],
                    is_ai_generated=True,
                    is_accepted=None,
                    source="original",
                    source_story_text=result.get("story", ""),
                    source_acceptance_criteria=result.get("acceptance_criteria", []),
                )
                
                risk = await self.repository.create(risk_create)
                created.append(risk)
                
            except Exception as e:
                logger.error(f"Failed to persist risk for story {result.get('issue_key')}: {e}")
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
        Crée des risques pour toutes les UserStories d'un projet/sprint/epic.
        Utilise le repository pour la création en lot.
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
    # MANUAL RISK CREATION (sans IA)
    # ============================================================
    
    async def create_risk_manual(self, data: RiskCreate) -> RiskResponse:
        """Création manuelle d'un risque (sans IA, is_ai_generated=False)."""
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
        """
        Get paginated list of risks with optional filters.
        Remplace get_by_test_plan() par get_all() avec filtres.
        """
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
        return [RiskResponse.model_validate(r) for r in risks]
    
    async def get_risks_by_sprint(
        self,
        project_id: str,
        sprint: str,
        level: Optional[str] = None,
        is_accepted: Optional[bool] = None,
    ) -> List[RiskResponse]:
        """Get all risks for a sprint via JOIN."""
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
        """Get all risks for an epic via JOIN."""
        items, _ = await self.repository.get_all(
            project_id=project_id,
            epic_key=epic_key,
            level=level,
        )
        return [RiskResponse.model_validate(r) for r in items]

    async def get_risk_summary_by_project(self, project_id: str) -> dict:
        """Get risk distribution summary for a project."""
        return await self.repository.get_risk_summary_by_project(project_id)
    
    async def get_risk_summary_by_sprint(self, project_id: str, sprint: str) -> dict:
        """Get risk distribution summary for a sprint."""
        return await self.repository.get_risk_summary_by_sprint(project_id, sprint)

    async def get_risks_by_user_story(self, user_story_id: str) -> List[RiskResponse]:
        """Get all risks for a user story."""
        risks = await self.repository.get_by_user_story(user_story_id)
        return [RiskResponse.model_validate(r) for r in risks]

    async def get_all_risks(
        self,
        project_id: Optional[str] = None,
        sprint: Optional[str] = None,
        epic_key: Optional[str] = None,
        level: Optional[str] = None,
        is_accepted: Optional[bool] = None,
        source: Optional[str] = None,
    ) -> List[RiskResponse]:
        """Get all risks with optional filters."""
        items, _ = await self.repository.get_all(
            project_id=project_id,
            sprint=sprint,
            epic_key=epic_key,
            level=level,
            is_accepted=is_accepted,
            source=source,
        )
        return [RiskResponse.model_validate(r) for r in items]
    
    async def get_high_priority_risks(
        self, 
        project_id: Optional[str] = None,
        min_score: int = 12      # ← High = 12+ (était float 2.5)
    ) -> List[RiskResponse]:
        """Get high or critical risks (High ≥ 12, Critical ≥ 20)."""
        risks = await self.repository.get_high_priority_risks(project_id, min_score)
        return [RiskResponse.model_validate(r) for r in risks]
    

    async def human_correct_risk(
        self,
        risk_id: str,
        probability: int,
        impact: int,
        modified_by: str,
        comment: Optional[str] = None,
    ) -> Optional[RiskResponse]:
        """
        Correction humaine d'un risque ML.
        Sauvegarde la correction pour réentraînement futur.
        """
        risk = await self.repository.get_by_id(risk_id)
        if not risk:
            return None
        
        # Sauvegarder les valeurs originales du ML
        risk.original_probability = risk.probability
        risk.original_impact = risk.impact
        
        # Appliquer la correction humaine
        risk.probability = probability
        risk.impact = impact
        risk.risk_score = probability * impact
        risk.level = classify_priority(risk.risk_score)  # à importer
        risk.is_accepted = True
        risk.source = "human_modified"
        risk.modified_by = modified_by
        risk.modified_at = datetime.now()
        
        # TODO: Sauvegarder dans la table feedback pour réentraînement
        
        await self.db.flush()
        await self.db.refresh(risk)
        await self.db.commit()
        
        return RiskResponse.model_validate(risk)
    
    # ============================================================
    # UPDATE (Risk Control - ISTQB §5.2.4)
    # ============================================================
    
    async def update_risk(self, risk_id: str, data: RiskUpdate) -> Optional[RiskResponse]:
        """Update a risk (recomputes score if P or I changed)."""
        risk = await self.repository.update(risk_id, data)
        if not risk:
            return None
        await self.db.commit()
        return RiskResponse.model_validate(risk)
    
    async def accept_risk(self, risk_id: str, accepted: bool) -> Optional[RiskResponse]:
        """Accept or reject a risk (ISTQB §5.2.4: validation par le testeur)."""
        risk = await self.repository.accept_risk(risk_id, accepted)
        if not risk:
            return None
        await self.db.commit()
        return RiskResponse.model_validate(risk)
    
    async def propose_mitigation(self, risk_id: str, mitigation: str) -> Optional[RiskResponse]:
        """Propose a mitigation strategy (ISTQB §5.2.4: Atténuation des risques)."""
        return await self.update_risk(risk_id, RiskUpdate(mitigation=mitigation))
    
    
    async def reanalyze_risk(
        self, 
        risk_id: str, 
        story: str,
        acceptance_criteria: List[str],
    ) -> Optional[RiskResponse]:
        """Ré-analyser un risque existant avec le nouveau pipeline."""
        risk = await self.repository.get_by_id(risk_id)
        if not risk:
            return None
        
        pipeline = await get_pipeline()
        result = await pipeline.run(
            user_story=story,
            acceptance_criteria=acceptance_criteria,
            user_story_id=risk.user_story_id,
        )
        
        if result.workflow_status == "error":
            raise ValueError(f"Re-analysis failed: {result.error}")
        
        risk.probability = result.probability
        risk.impact = result.impact
        risk.risk_score = result.risk_score
        risk.level = result.priority     # "critical", "high", etc.
        risk.description = result.description
        risk.mitigation = result.mitigation
        risk.reasoning = result.reasoning
        risk.is_ai_generated = True
        risk.is_accepted = None
        risk.source = result.source
        risk.ml_confidence = result.ml_confidence
        
        await self.db.flush()
        await self.db.refresh(risk)
        await self.db.commit()
        
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
        """Delete all risks for a project (via JOIN UserStory)."""
        count = await self.repository.delete_by_project(project_id)
        await self.db.commit()
        return count