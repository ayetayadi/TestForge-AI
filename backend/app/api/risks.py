"""API endpoints for Risk management with AI analysis (ISTQB)."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from pydantic import BaseModel, Field

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.schemas.risk_schema import (
    RiskCreate,
    RiskUpdate,
    RiskResponse,
    RiskFilters,
    RiskListResponse,
    RiskBatchResponse,
)
from app.services.risk_service import RiskService
from app.workers.risk_worker import submit_risk_job

router = APIRouter(prefix="/risks", tags=["Risks"])


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class UserStoryAnalysisRequest(BaseModel):
    """Request body for AI-powered user story analysis."""
    story: str
    acceptance_criteria: List[str] = []
    user_story_id: Optional[str] = None


class BatchAnalysisRequest(BaseModel):
    """Request body for batch analysis of multiple user stories."""
    project_id: str
    stories: List[UserStoryAnalysisRequest]
    concurrency: int = 3


class ProjectAnalysisRequest(BaseModel):
    """Request body for project-wide risk analysis with filters."""
    project_id: str
    limit: Optional[int] = Field(None, ge=1, description="Limit number of stories to analyze (max 100)")
    epic_keys: Optional[List[str]] = Field(None, description="Filter by epic keys")
    sprint_ids: Optional[List[str]] = Field(None, description="Filter by sprint IDs")
    jira_priorities: Optional[List[str]] = Field(None, description="Filter by priorities")
    min_story_points: Optional[float] = Field(None, ge=0, description="Minimum story points")
    use_approved_version_only: bool = Field(False, description="Use approved version only")
    force_reanalyze: bool = Field(False, description="Force reanalysis even if already analyzed")


# ============================================================
# AI-POWERED ENDPOINTS (ISTQB PIPELINE)
# ============================================================

@router.post(
    "/analyze-project",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Launch risk analysis for user stories with filters",
)
async def analyze_project_risks(
    request: ProjectAnalysisRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Lance l'analyse avec filtres - priority order: Highest → High → Medium → Low"""
    
    from sqlalchemy import select, case
    from app.models.user_story import UserStory
    from app.repositories.risk_repository import RiskRepository
    
    print(f"🔵 RECEIVED analyze-project request")
    print(f"📦 Request body: {request.model_dump()}")

    priority_order = {
        "Highest": 1, "High": 2, "Medium": 3, "Low": 4, None: 5
    }
    
    # Build query with filters
    query = select(UserStory).where(UserStory.project_id == request.project_id)
    filters_applied = []

    if request.epic_keys:
        query = query.where(
            or_(
                UserStory.epic_key.in_(request.epic_keys),
                UserStory.epic_name.in_(request.epic_keys)
            )
        )
        filters_applied.append(f"epic_keys={request.epic_keys}")
    
    if request.sprint_ids:
        query = query.where(UserStory.sprint.in_(request.sprint_ids))
        filters_applied.append(f"sprint_ids={request.sprint_ids}")
    
    if request.jira_priorities:
        query = query.where(UserStory.priority.in_(request.jira_priorities))
        filters_applied.append(f"jira_priorities={request.jira_priorities}")
    
    if request.min_story_points is not None:
        query = query.where(UserStory.story_points >= request.min_story_points)
        filters_applied.append(f"min_story_points={request.min_story_points}")

    # Apply sorting by priority
    query = query.order_by(
        case(
            *[(UserStory.priority == priority, order) for priority, order in priority_order.items() if priority],
            else_=5
        ),
        UserStory.story_points.desc().nulls_last(),
        UserStory.created_at.asc()
    )
    
    if request.limit:
        query = query.limit(request.limit)
    
    result = await db.execute(query)
    stories = result.scalars().all()
    
    if not stories:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user stories found with the specified filters: {filters_applied}",
        )
    
    # Check already analyzed stories
    if not request.force_reanalyze:
        risk_repo = RiskRepository(db)
        stories_to_analyze = []
        for story in stories:
            existing = await risk_repo.get_by_user_story(story.id)
            if not existing:
                stories_to_analyze.append(story)
        
        analyzed_count = len(stories) - len(stories_to_analyze)
        stories = stories_to_analyze
        
        if not stories:
            return {
                "submitted": 0,
                "message": "All matching user stories already analyzed. Use force_reanalyze=true to re-analyze.",
                "already_analyzed": analyzed_count,
            }
    
    # Submit jobs
    job_ids = []
    priority_stats = {"Highest": 0, "High": 0, "Medium": 0, "Low": 0, "None": 0}
    
    for story in stories:
        job_id = f"{request.project_id}-{story.id}"
        await submit_risk_job({
            "job_id": job_id,
            "project_id": request.project_id,
            "user_story_id": story.id,
            "issue_key": story.issue_key,
            "jira_priority": story.priority,
            "story_points": story.story_points,
            "components": story.components or [],
            "labels": story.labels or [],
            "epic": story.epic_key,
            "use_approved_version_only": request.use_approved_version_only,
        })
        job_ids.append(job_id)
        priority = story.priority if story.priority in priority_stats else "None"
        priority_stats[priority] += 1
    
    return {
        "submitted": len(job_ids),
        "project_id": request.project_id,
        "job_ids": job_ids,
        "priority_breakdown": {k: v for k, v in priority_stats.items() if v > 0},
        "filters_applied": {
            "epic_keys": request.epic_keys,
            "sprint_ids": request.sprint_ids,
            "priorities": request.jira_priorities,
            "min_points": request.min_story_points,
            "limit": request.limit,
            "use_approved_version_only": request.use_approved_version_only,
        },
        "message": f"{len(job_ids)} risk analysis jobs queued.",
    }


@router.get(
    "/pending-count",
    summary="Get count of pending user stories to analyze",
)
async def get_pending_analysis_count(
    project_id: str = Query(...),
    epic_keys: Optional[str] = Query(None, description="Comma-separated epic keys"),
    sprint_ids: Optional[str] = Query(None, description="Comma-separated sprint IDs"),
    jira_priorities: Optional[str] = Query(None, description="Comma-separated priorities"),
    min_story_points: Optional[float] = None,
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Retourne le nombre de US non encore analysées selon les filtres"""
    
    from app.models.user_story import UserStory
    from app.models.risk import Risk
    
    epic_list = epic_keys.split(',') if epic_keys else None
    sprint_list = sprint_ids.split(',') if sprint_ids else None
    priority_list = jira_priorities.split(',') if jira_priorities else None
    
    # Total stories matching filters
    total_query = select(func.count(UserStory.id)).where(
        UserStory.project_id == project_id
    )
    
    if epic_list:
        total_query = total_query.where(
            or_(
                UserStory.epic_key.in_(epic_list),
                UserStory.epic_name.in_(epic_list)
            )
        )
    if sprint_list:
        total_query = total_query.where(UserStory.sprint.in_(sprint_list))
    if priority_list:
        total_query = total_query.where(UserStory.priority.in_(priority_list))
    if min_story_points is not None:
        total_query = total_query.where(UserStory.story_points >= min_story_points)
    
    total_stories = await db.scalar(total_query) or 0
    
    # Already analyzed stories (via Risk.user_story_id)
    analyzed_subquery = select(Risk.user_story_id.distinct()).where(Risk.user_story_id.isnot(None))
    
    analyzed_query = select(func.count(UserStory.id)).where(
        UserStory.project_id == project_id,
        UserStory.id.in_(analyzed_subquery)
    )
    
    if epic_list:
        analyzed_query = analyzed_query.where(
            or_(
                UserStory.epic_key.in_(epic_list),
                UserStory.epic_name.in_(epic_list)
            )
        )
    if sprint_list:
        analyzed_query = analyzed_query.where(UserStory.sprint.in_(sprint_list))
    if priority_list:
        analyzed_query = analyzed_query.where(UserStory.priority.in_(priority_list))
    if min_story_points is not None:
        analyzed_query = analyzed_query.where(UserStory.story_points >= min_story_points)
    
    analyzed_stories = await db.scalar(analyzed_query) or 0
    
    pending_count = max(0, total_stories - analyzed_stories)
    
    # Priority breakdown of pending stories
    priority_breakdown = {}
    if pending_count > 0:
        for priority in ['Highest', 'High', 'Medium', 'Low']:
            priority_query = select(func.count(UserStory.id)).where(
                UserStory.project_id == project_id,
                UserStory.priority == priority,
                ~UserStory.id.in_(analyzed_subquery)
            )
            if epic_list:
                priority_query = priority_query.where(
                    or_(                                      
                        UserStory.epic_key.in_(epic_list),
                        UserStory.epic_name.in_(epic_list)
                    )
                )
            if sprint_list:
                priority_query = priority_query.where(UserStory.sprint.in_(sprint_list))
            
            count = await db.scalar(priority_query) or 0
            if count > 0:
                priority_breakdown[priority] = count
    
    return {
        "total_stories": total_stories,
        "analyzed_stories": analyzed_stories,
        "pending_stories": pending_count,
        "priority_breakdown": priority_breakdown,
        "has_pending": pending_count > 0,
        "filters_applied": {
            "epic_keys": epic_list,
            "sprint_ids": sprint_list,
            "priorities": priority_list,
            "min_points": min_story_points,
        }
    }


@router.post(
    "/analyze",
    response_model=RiskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Analyze a user story with AI (ISTQB)",
)
async def analyze_user_story(
    request: UserStoryAnalysisRequest,
    project_id: str = Query(..., description="ID du projet (contexte)"),
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Analyse une User Story avec l'IA et crée le risque associé."""
    service = RiskService(db)
    return await service.analyze_user_story(
        story=request.story,
        acceptance_criteria=request.acceptance_criteria,
        project_id=project_id,
        user_story_id=request.user_story_id,
    )


@router.post(
    "/analyze/batch",
    response_model=RiskBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Batch analyze multiple user stories",
)
async def analyze_user_stories_batch(
    request: BatchAnalysisRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> RiskBatchResponse:
    """Analyse un lot de User Stories avec l'IA."""
    service = RiskService(db)
    stories_data = [
        {
            "story": s.story,
            "acceptance_criteria": s.acceptance_criteria,
            "user_story_id": s.user_story_id,
        }
        for idx, s in enumerate(request.stories)
    ]
    return await service.analyze_user_stories_batch(
        stories_data=stories_data,
        project_id=request.project_id,
        concurrency=request.concurrency,
    )


@router.post(
    "/manual",
    response_model=RiskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a risk manually (no AI)",
)
async def create_risk_manual(
    data: RiskCreate,
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Création manuelle d'un risque (sans utilisation de l'IA)."""
    service = RiskService(db)
    return await service.create_risk_manual(data)


# ============================================================
# READ ENDPOINTS
# ============================================================

@router.get(
    "/project/{project_id}",
    response_model=List[RiskResponse],
    summary="Get all risks for a project",
)
async def get_risks_by_project(
    project_id: str,
    level: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
    is_accepted: Optional[bool] = None,
    is_ai_generated: Optional[bool] = None,
    db: AsyncSession = Depends(deps.get_db),
) -> List[RiskResponse]:
    """Get all risks for a project with optional filters."""
    service = RiskService(db)
    return await service.get_risks_by_project(
        project_id=project_id,
        level=level,
        is_accepted=is_accepted,
        is_ai_generated=is_ai_generated,
    )


@router.get(
    "/project/{project_id}/sprint/{sprint}",
    response_model=List[RiskResponse],
    summary="Get all risks for a sprint",
)
async def get_risks_by_sprint(
    project_id: str,
    sprint: str,
    level: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
    is_accepted: Optional[bool] = None,
    db: AsyncSession = Depends(deps.get_db),
) -> List[RiskResponse]:
    """Get all risks for a specific sprint."""
    service = RiskService(db)
    return await service.get_risks_by_sprint(
        project_id=project_id,
        sprint=sprint,
        level=level,
        is_accepted=is_accepted,
    )


@router.get(
    "/project/{project_id}/epic/{epic_key}",
    response_model=List[RiskResponse],
    summary="Get all risks for an epic",
)
async def get_risks_by_epic(
    project_id: str,
    epic_key: str,
    level: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
    db: AsyncSession = Depends(deps.get_db),
) -> List[RiskResponse]:
    """Get all risks for a specific epic."""
    service = RiskService(db)
    return await service.get_risks_by_epic(
        project_id=project_id,
        epic_key=epic_key,
        level=level,
    )


@router.get(
    "/project/{project_id}/summary",
    response_model=dict,
    summary="Get risk distribution summary for a project",
)
async def get_risk_summary_by_project(
    project_id: str,
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Get summary statistics for risks in a project."""
    service = RiskService(db)
    return await service.get_risk_summary_by_project(project_id)


@router.get(
    "/project/{project_id}/sprint/{sprint}/summary",
    response_model=dict,
    summary="Get risk distribution summary for a sprint",
)
async def get_risk_summary_by_sprint(
    project_id: str,
    sprint: str,
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Get summary statistics for risks in a sprint."""
    service = RiskService(db)
    return await service.get_risk_summary_by_sprint(project_id, sprint)


@router.get(
    "/user-story/{user_story_id}",
    response_model=List[RiskResponse],
    summary="Get all risks for a user story",
)
async def get_risks_by_user_story(
    user_story_id: str,
    db: AsyncSession = Depends(deps.get_db),
) -> List[RiskResponse]:
    """Get all risks associated with a specific user story."""
    service = RiskService(db)
    return await service.get_risks_by_user_story(user_story_id)


@router.get(
    "/all",
    response_model=List[RiskResponse],
    summary="Get all risks with optional filters",
)
async def get_all_risks(
    project_id: Optional[str] = Query(None),
    sprint: Optional[str] = Query(None),
    epic_key: Optional[str] = Query(None),
    level: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
    is_accepted: Optional[bool] = Query(None),
    source: Optional[str] = Query(None, pattern="^(original|approved_version)$"),
    db: AsyncSession = Depends(deps.get_db),
) -> List[RiskResponse]:
    """Get all risks across all projects with optional filters."""
    service = RiskService(db)
    return await service.get_all_risks(
        project_id=project_id,
        sprint=sprint,
        epic_key=epic_key,
        level=level,
        is_accepted=is_accepted,
        source=source,
    )


@router.get(
    "/high-priority",
    response_model=List[RiskResponse],
    summary="Get high/critical risks",
)
async def get_high_priority_risks(
    project_id: Optional[str] = Query(None),
    min_score: float = Query(12, ge=0, le=4.5),
    db: AsyncSession = Depends(deps.get_db),
) -> List[RiskResponse]:
    """Get risks with score >= threshold (ISTQB: Haute ou Critique)."""
    service = RiskService(db)
    return await service.get_high_priority_risks(project_id, min_score)


@router.get(
    "/rate-limit-status",
    summary="Check current rate limit status",
)
async def get_rate_limit_status(
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Retourne le statut actuel du rate limiting."""
    from app.models.user_story import UserStory
    from app.models.risk import Risk
    
    query = select(func.count(UserStory.id)).where(
        ~UserStory.id.in_(select(Risk.user_story_id).where(Risk.is_ai_generated == True))
    )
    pending_count = await db.execute(query)
    pending = pending_count.scalar() or 0
    
    return {
        "pending_analyses": pending,
        "estimated_time_minutes": round(pending * 3 / 60, 1),
        "rate_limit_tpm": 12000,
        "recommended_batch_size": 10,
        "message": "Analyse par lots de 10 US maximum recommandée",
    }


@router.get(
    "/{risk_id}",
    response_model=RiskResponse,
    summary="Get risk by ID",
)
async def get_risk(
    risk_id: str,
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Get a single risk."""
    service = RiskService(db)
    risk = await service.get_risk(risk_id)
    if not risk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk {risk_id} not found",
        )
    return risk


# ============================================================
# UPDATE ENDPOINTS
# ============================================================

@router.patch(
    "/{risk_id}",
    response_model=RiskResponse,
    summary="Update a risk",
)
async def update_risk(
    risk_id: str,
    data: RiskUpdate,
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Update a risk. If P or I changes, risk_score and level are recomputed."""
    service = RiskService(db)
    risk = await service.update_risk(risk_id, data)
    if not risk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk {risk_id} not found",
        )
    return risk


@router.patch(
    "/{risk_id}/accept",
    response_model=RiskResponse,
    summary="Accept or reject a risk",
)
async def accept_risk(
    risk_id: str,
    accepted: bool = Query(..., description="True to accept, False to reject"),
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Accept (true) or reject (false) a risk."""
    service = RiskService(db)
    risk = await service.accept_risk(risk_id, accepted)
    if not risk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk {risk_id} not found",
        )
    return risk


@router.patch(
    "/{risk_id}/mitigation",
    response_model=RiskResponse,
    summary="Propose mitigation actions",
)
async def propose_mitigation(
    risk_id: str,
    mitigation: str = Body(..., min_length=3, embed=True),
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Add or update mitigation actions for a risk."""
    service = RiskService(db)
    risk = await service.propose_mitigation(risk_id, mitigation)
    if not risk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk {risk_id} not found",
        )
    return risk


@router.post(
    "/{risk_id}/reanalyze",
    response_model=RiskResponse,
    summary="Re-analyze a risk with AI",
)
async def reanalyze_risk(
    risk_id: str,
    story: str = Body(...),
    acceptance_criteria: List[str] = Body(default=[]),
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Réanalyse un risque existant (quand la User Story change)."""
    service = RiskService(db)
    risk = await service.reanalyze_risk(risk_id, story, acceptance_criteria)
    if not risk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk {risk_id} not found",
        )
    return risk


# ============================================================
# DELETE ENDPOINTS
# ============================================================

@router.delete(
    "/{risk_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a risk",
)
async def delete_risk(
    risk_id: str,
    db: AsyncSession = Depends(deps.get_db),
) -> None:
    """Delete a single risk."""
    service = RiskService(db)
    deleted = await service.delete_risk(risk_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk {risk_id} not found",
        )
    return None


@router.delete(
    "/project/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete all risks for a project",
)
async def delete_project_risks(
    project_id: str,
    db: AsyncSession = Depends(deps.get_db),
) -> None:
    """Delete all risks associated with a project."""
    service = RiskService(db)
    await service.delete_project_risks(project_id)
    return None


class HumanCorrectionRequest(BaseModel):
    probability: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    modified_by: str
    comment: Optional[str] = None

@router.patch(
    "/{risk_id}/human-correct",
    response_model=RiskResponse,
    summary="Human correction of ML risk analysis",
)
async def human_correct_risk(
    risk_id: str,
    correction: HumanCorrectionRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Correction humaine d'un risque prédit par le ML."""
    service = RiskService(db)
    risk = await service.human_correct_risk(
        risk_id=risk_id,
        probability=correction.probability,
        impact=correction.impact,
        modified_by=correction.modified_by,
        comment=correction.comment,
    )
    if not risk:
        raise HTTPException(status_code=404, detail=f"Risk {risk_id} not found")
    return risk