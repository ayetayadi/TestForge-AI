"""API endpoints for Risk management with LLM-based analysis (Risk Based Testing)."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.schemas.risk_schema import (
    RiskCreate,
    RiskUpdate,
    RiskResponse,
    RiskFilters,
    RiskListResponse,
    RiskBatchResponse,
    RiskSummary,
)
from app.services.risk_service import RiskService
from app.workers.risk_worker import submit_risk_job

router = APIRouter(prefix="/risks", tags=["Risks"])

logger = logging.getLogger(__name__)


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class UserStoryAnalysisRequest(BaseModel):
    """Request body for LLM-powered user story risk analysis."""
    story: str = Field(..., description="The user story text to analyze")
    acceptance_criteria: List[str] = Field(
        default_factory=list,
        description="Acceptance criteria for the story"
    )
    user_story_id: Optional[str] = Field(
        None,
        description="Existing user story ID (if already in database)"
    )
    issue_key: Optional[str] = Field(
        None,
        description="Jira issue key (e.g., PROJ-123)"
    )
    test_plan_id: Optional[str] = Field(
        None,
        description="Optional test plan to link the risk to"
    )


class BatchAnalysisRequest(BaseModel):
    """Request body for batch analysis of multiple user stories."""
    project_id: str = Field(..., description="Project ID for context")
    stories: List[UserStoryAnalysisRequest] = Field(..., min_length=1)
    test_plan_id: Optional[str] = Field(None)
    concurrency: int = Field(2, ge=1, le=5, description="Max parallel LLM calls")


class ProjectAnalysisRequest(BaseModel):
    """Request body for project-wide risk analysis with filters."""
    project_id: str
    limit: Optional[int] = Field(
        None, ge=1, le=100,
        description="Limit number of stories to analyze (max 100)"
    )
    epic_keys: Optional[List[str]] = Field(None, description="Filter by epic keys")
    sprint_ids: Optional[List[str]] = Field(None, description="Filter by sprint IDs")
    jira_priorities: Optional[List[str]] = Field(
        None, description="Filter by Jira priorities"
    )
    min_story_points: Optional[float] = Field(
        None, ge=0, description="Minimum story points"
    )
    use_approved_version_only: bool = Field(
        False, description="Use approved version of stories only"
    )
    force_reanalyze: bool = Field(
        False, description="Force reanalysis even if already analyzed"
    )


class HumanCorrectionRequest(BaseModel):
    """Request body for human correction of LLM-generated risk."""
    probability: int = Field(
        ..., ge=1, le=5,
        description="Corrected probability (1-5)"
    )
    impact: int = Field(
        ..., ge=1, le=5,
        description="Corrected impact (1-5)"
    )
    comment: Optional[str] = Field(None, description="Reason for correction")


# ============================================================
# AI-POWERED ENDPOINTS (LLM PIPELINE)
# ============================================================

@router.post(
    "/analyze-project",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Launch LLM risk analysis for project stories with filters",
)
async def analyze_project_risks(
    request: ProjectAnalysisRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """
    Launch LLM risk analysis for user stories matching filters.
    
    Priority order: Highest → High → Medium → Low → None.
    Returns immediately with job IDs - analysis runs asynchronously.
    """
    from app.models.user_story import UserStory
    from app.repositories.risk_repository import RiskRepository
    
    logger.info(f" analyze-project request: {request.model_dump()}")

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

    # Sort by priority (Highest first), then story points (desc), then creation date
    query = query.order_by(
        case(
            *[(UserStory.priority == p, o) for p, o in priority_order.items() if p],
            else_=5
        ),
        UserStory.story_points.desc().nulls_last(),
        UserStory.created_at.asc()
    )
    
    result = await db.execute(query)
    stories = result.scalars().all()

    if not stories:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No user stories found with filters: {filters_applied}",
        )

    # Handle reanalysis logic
    already_analyzed = 0
    not_eligible = 0

    from app.repositories.risk_repository import RiskRepository
    from app.repositories.user_story_version_repository import get_approved_version_for_risk

    risk_repo = RiskRepository(db)

    if not request.force_reanalyze:
        stories_to_analyze = []
        for story in stories:
            existing = await risk_repo.get_by_user_story(story.id)
            if not existing:
                stories_to_analyze.append(story)
            else:
                already_analyzed += 1

        if not stories_to_analyze:
            return {
                "submitted": 0,
                "message": "All matching stories already analyzed. Use force_reanalyze=true to re-analyze modified stories.",
                "already_analyzed": already_analyzed,
            }
        if request.limit:
            stories_to_analyze = stories_to_analyze[:request.limit]
        stories = stories_to_analyze
    else:
        # force_reanalyze: only allow stories modified since their last analysis
        stories_to_analyze = []
        for story in stories:
            existing = await risk_repo.get_by_user_story(story.id)
            if not existing:
                # Never analyzed → always include
                stories_to_analyze.append(story)
                continue
            last_risk = max(existing, key=lambda r: r.created_at)
            # Condition A: story re-synced from Jira after last analysis
            jira_ts = story.jira_updated_at or story.updated_at
            cond_a = jira_ts is not None and jira_ts > last_risk.created_at
            # Condition B: new approved refinement version after last analysis
            approved = await get_approved_version_for_risk(db, story.id)
            cond_b = approved is not None and approved.started_at > last_risk.created_at
            if cond_a or cond_b:
                stories_to_analyze.append(story)
            else:
                not_eligible += 1

        if not stories_to_analyze:
            return {
                "submitted": 0,
                "message": "No eligible stories for re-analysis. Stories must be modified in Jira or have a new approved refinement version since their last analysis.",
                "already_analyzed": already_analyzed,
                "not_eligible": not_eligible,
            }
        if request.limit:
            stories_to_analyze = stories_to_analyze[:request.limit]
        stories = stories_to_analyze
    
    # Submit jobs to worker
    job_ids = []
    priority_stats = {"Highest": 0, "High": 0, "Medium": 0, "Low": 0, "None": 0}
    
    for story in stories:
        job_id = f"{request.project_id}-{story.id}"
        await submit_risk_job({
            "job_id": job_id,
            "project_id": request.project_id,
            "user_story_id": story.id,
            "issue_key": story.issue_key,
            "story_title": story.title,
            "story_description": story.description or "",
            "acceptance_criteria": story.acceptance_criteria or [],
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
        "already_analyzed": already_analyzed,
        "filters_applied": filters_applied,
        "message": f"{len(job_ids)} risk analysis jobs queued successfully.",
    }


@router.get(
    "/pending-count",
    summary="Get count of stories pending risk analysis",
)
async def get_pending_analysis_count(
    project_id: str = Query(..., description="Project ID"),
    epic_keys: Optional[str] = Query(None, description="Comma-separated epic keys"),
    sprint_ids: Optional[str] = Query(None, description="Comma-separated sprint IDs"),
    jira_priorities: Optional[str] = Query(None, description="Comma-separated priorities"),
    min_story_points: Optional[float] = None,
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Get count of user stories that haven't been analyzed yet."""
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
            or_(UserStory.epic_key.in_(epic_list), UserStory.epic_name.in_(epic_list))
        )
    if sprint_list:
        total_query = total_query.where(UserStory.sprint.in_(sprint_list))
    if priority_list:
        total_query = total_query.where(UserStory.priority.in_(priority_list))
    if min_story_points is not None:
        total_query = total_query.where(UserStory.story_points >= min_story_points)
    
    total_stories = await db.scalar(total_query) or 0
    
    # Already analyzed stories (have at least one Risk)
    analyzed_subquery = select(Risk.user_story_id.distinct()).where(
        Risk.user_story_id.isnot(None)
    )
    
    analyzed_query = select(func.count(UserStory.id)).where(
        UserStory.project_id == project_id,
        UserStory.id.in_(analyzed_subquery)
    )
    
    if epic_list:
        analyzed_query = analyzed_query.where(
            or_(UserStory.epic_key.in_(epic_list), UserStory.epic_name.in_(epic_list))
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
                    or_(UserStory.epic_key.in_(epic_list), UserStory.epic_name.in_(epic_list))
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
        "completion_percentage": round(analyzed_stories / total_stories * 100, 1) if total_stories > 0 else 0,
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
    summary="Analyze a single user story with LLM",
)
async def analyze_user_story(
    request: UserStoryAnalysisRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """
    Analyze a single user story with LLM for risk assessment.
    
    Returns P (1-5), I (1-5), Score = P × I, Level, and test recommendations.
    """
    service = RiskService(db)
    return await service.analyze_user_story(
        story=request.story,
        acceptance_criteria=request.acceptance_criteria,
        user_story_id=request.user_story_id,
        issue_key=request.issue_key or "?",
        test_plan_id=request.test_plan_id,
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
    """Analyze multiple user stories in batch with LLM."""
    service = RiskService(db)
    stories_data = [
        {
            "story": s.story,
            "acceptance_criteria": s.acceptance_criteria,
            "user_story_id": s.user_story_id,
            "issue_key": s.issue_key or "?",
        }
        for s in request.stories
    ]
    return await service.analyze_user_stories_batch(
        stories_data=stories_data,
        test_plan_id=request.test_plan_id,
        concurrency=request.concurrency,
    )


@router.post(
    "/manual",
    response_model=RiskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a risk manually (no LLM)",
)
async def create_risk_manual(
    data: RiskCreate,
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Create a risk manually without using LLM analysis."""
    service = RiskService(db)
    return await service.create_risk_manual(data)


# ============================================================
# READ ENDPOINTS
# ============================================================

@router.get("/all", response_model=List[RiskResponse],
    summary="Get all risks with optional filters")
async def get_all_risks(
    project_id: Optional[str] = Query(None),
    sprint: Optional[str] = Query(None),
    epic_key: Optional[str] = Query(None),
    level: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
    is_accepted: Optional[bool] = Query(None),
    source: Optional[str] = Query(None),
    db: AsyncSession = Depends(deps.get_db),
    current_user: deps.User = Depends(deps.get_current_user),
) -> List[RiskResponse]:
    """Get all risks for the current user's projects with optional filters."""
    from app.api.deps import get_user_project_ids
    project_ids = await get_user_project_ids(db, current_user.id)
    service = RiskService(db)
    return await service.get_all_risks(
        project_id=project_id, sprint=sprint, epic_key=epic_key,
        level=level, is_accepted=is_accepted, source=source,
        project_ids=project_ids,
    )

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
    "/project/{project_id}/summary",
    response_model=RiskSummary,
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
    response_model=RiskSummary,
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
    "/project/{project_id}/epic/{epic_key}/summary",
    response_model=RiskSummary,
    summary="Get risk distribution summary for an epic",
)
async def get_risk_summary_by_epic(
    project_id: str,
    epic_key: str,
    db: AsyncSession = Depends(deps.get_db),
) -> dict:
    """Get summary statistics for risks in an epic."""
    service = RiskService(db)
    return await service.get_risk_summary_by_epic(project_id, epic_key)


@router.get(
    "/high-priority",
    response_model=List[RiskResponse],
    summary="Get high/critical risks",
)
async def get_high_priority_risks(
    project_id: Optional[str] = Query(None),
    min_score: int = Query(
        12, ge=1, le=25,
        description="Minimum risk score (12=High, 20=Critical)"
    ),
    db: AsyncSession = Depends(deps.get_db),
) -> List[RiskResponse]:
    """
    Get risks with score >= threshold.
    Document original: High ≥ 12, Critical ≥ 20.
    """
    service = RiskService(db)
    return await service.get_high_priority_risks(
        project_id=project_id,
        min_score=min_score,
    )


@router.get(
    "/critical",
    response_model=List[RiskResponse],
    summary="Get critical risks only (score ≥ 20)",
)
async def get_critical_risks(
    project_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(deps.get_db),
) -> List[RiskResponse]:
    """Get critical risks (score ≥ 20) that require comprehensive testing."""
    service = RiskService(db)
    return await service.get_critical_risks(project_id=project_id)


@router.get(
    "/list",
    response_model=RiskListResponse,
    summary="List risks with pagination and filters",
)
async def list_risks(
    project_id: Optional[str] = Query(None),
    sprint: Optional[str] = Query(None),
    epic_key: Optional[str] = Query(None),
    user_story_id: Optional[str] = Query(None),
    level: Optional[str] = Query(None, pattern="^(critical|high|medium|low)$"),
    is_accepted: Optional[bool] = Query(None),
    source: Optional[str] = Query(None, pattern="^(llm|original|approved_version|human_modified|manual)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(deps.get_db),
) -> RiskListResponse:
    """Get paginated list of risks with optional filters."""
    service = RiskService(db)
    return await service.list_risks(
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


@router.get(
    "/{risk_id}",
    response_model=RiskResponse,
    summary="Get a single risk by ID",
)
async def get_risk(
    risk_id: str,
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Get a single risk by its ID."""
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
    """
    Update a risk. If P or I changes, Score, Level, and test 
    recommendations are automatically recomputed.
    """
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
    summary="Accept or reject a risk analysis",
)
async def accept_risk(
    risk_id: str,
    accepted: bool = Query(..., description="True to accept, False to reject"),
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Accept (true) or reject (false) a risk analysis."""
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
    summary="Update mitigation strategy",
)
async def propose_mitigation(
    risk_id: str,
    mitigation: str = Body(..., min_length=3, max_length=5000, embed=True),
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """Add or update the mitigation strategy for a risk."""
    service = RiskService(db)
    risk = await service.propose_mitigation(risk_id, mitigation)
    if not risk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk {risk_id} not found",
        )
    return risk


@router.patch(
    "/{risk_id}/human-correct",
    response_model=RiskResponse,
    summary="Human correction of LLM-generated risk",
)
async def human_correct_risk(
    risk_id: str,
    correction: HumanCorrectionRequest,
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """
    QA lead corrects an LLM-generated risk analysis.
    Overrides P and I values with human judgment.
    """
    service = RiskService(db)
    risk = await service.human_correct_risk(
        risk_id=risk_id,
        probability=correction.probability,
        impact=correction.impact,
        comment=correction.comment,
    )
    if not risk:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Risk {risk_id} not found",
        )
    return risk


@router.post(
    "/{risk_id}/reanalyze",
    response_model=RiskResponse,
    summary="Re-analyze a risk with LLM",
)
async def reanalyze_risk(
    risk_id: str,
    story: str = Body(..., description="Updated user story text"),
    acceptance_criteria: List[str] = Body(
        default_factory=list,
        description="Updated acceptance criteria"
    ),
    db: AsyncSession = Depends(deps.get_db),
) -> RiskResponse:
    """
    Re-analyze an existing risk when the user story changes.
    Runs fresh LLM analysis with updated story and ACs.
    """
    service = RiskService(db)
    try:
        risk = await service.reanalyze_risk(risk_id, story, acceptance_criteria)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
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
    """Delete a single risk by ID."""
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
    count = await service.delete_project_risks(project_id)
    logger.info(f"Deleted {count} risks for project {project_id}")
    return None