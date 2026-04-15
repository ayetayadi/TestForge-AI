# ============================================================
# app/services/job_service.py (CORRIGÉ)
# ============================================================
from typing import Dict, List, Any, Tuple, Optional
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import StoryDecision
from app.models.job import Job
from app.models.user_story import UserStory
from app.repositories.job_repository import create_job
from app.repositories.user_story_repository import get_user_story_by_id
from app.repositories.user_story_version_repository import (
    get_version_by_id,
    get_latest_version,
    get_versions_by_story_id
)
from app.workers.asyncio_workers import submit_job
from app.ai_agents_v2.user_story_refinement.utils.text_processing import detect_language


async def start_job(
    db: AsyncSession,
    user_story,
    reset: bool = False
) -> Tuple[str, Dict[str, Any]]:
    """
    Start a new job for a user story.
    
    Args:
        db: Database session
        user_story: User story object
        reset: If True, use original story + AC
        
    Returns:
        Tuple[job_id, state]
    """
    
    latest = await get_latest_version(db, user_story.id)
    
    print(f"[START_JOB] {user_story.issue_key}")
    print(f"[START_JOB] latest_version exists: {latest is not None}")

    # ============================================================
    # Determine input story + AC
    # ============================================================
    if reset:
        # Use original story
        raw_story = user_story.description
        acceptance_criteria = user_story.acceptance_criteria or []
    else:
        # Use latest version or original
        raw_story = (
            latest.improved_story
            if latest else user_story.description
        )
        acceptance_criteria = (
            latest.generated_acceptance_criteria
            if latest else user_story.acceptance_criteria or []
        )

    # ============================================================
    # Create job in DB
    # ============================================================
    job_id = str(uuid.uuid4())
    
    try:
        language = detect_language(raw_story)
    except Exception:
        language = "en"
    
    await create_job(db, job_id, user_story.id)

    # ============================================================
    # Create state for orchestrator
    # ============================================================
    state = {
        "job_id": job_id,
        "jira_id": user_story.issue_key,
        "raw_story": raw_story,
        "user_story_id": user_story.id,
        "acceptance_criteria": user_story.acceptance_criteria,
        "language": language
    }
    
    print(f"[START_JOB] {user_story.issue_key}")
    print(f"  - Story: {raw_story[:50]}...")
    print(f"  - AC count: {len(user_story.acceptance_criteria or [])}")
    print(f"  - Detected language: {language}")
    
    return job_id, state


async def apply_decision(
    db: AsyncSession,
    user_story_id: str,
    decision: str,
    version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Apply user decision to a version.
    
    Decisions:
    - approve: Mark version as approved
    - reject_relaunch: Reject and start new job
    - reject_keep: Reject but keep original
    
    Args:
        db: Database session
        user_story_id: User story ID
        decision: Decision type
        version_id: Version ID (required for approve/reject_relaunch)
        
    Returns:
        Result dict
    """
    
    try:
        # ============================================================
        # Get user story
        # ============================================================
        user_story = await get_user_story_by_id(db, user_story_id)

        if not user_story:
            raise HTTPException(404, "User story not found")

        # ============================================================
        # Validate decision + version_id
        # ============================================================
        if decision in ("approve", "reject_relaunch", "reject_keep"):
            if not version_id:
                raise HTTPException(400, "version_id is required")

        # ============================================================
        # Get version
        # ============================================================
        version = await get_version_by_id(db, version_id) if version_id else None

        if version_id and not version:
            raise HTTPException(404, "Version not found")

        if version and version.user_story_id != user_story_id:
            raise HTTPException(400, "Version does not belong to this story")

        # ============================================================
        # APPROVE
        # ============================================================
        if decision == "approve":
            
            # Mark all other versions as rejected
            versions = await get_versions_by_story_id(db, user_story_id)

            for v in versions:
                if v.id != version.id:
                    v.decision_status = StoryDecision.REJECTED

            # Mark this version as approved
            version.decision_status = StoryDecision.APPROVED

            await db.commit()

            return {"message": "Version approved"}

        # ============================================================
        # REJECT + RELAUNCH
        # ============================================================
        elif decision == "reject_relaunch":
            
            # Mark version as rejected
            version.decision_status = StoryDecision.REJECTED

            # Start new job with original story
            new_job_id, state = await start_job(
                db,
                user_story,
                reset=True
            )

            await db.commit()

            # Submit job
            try:
                await submit_job(state)
            except Exception as e:
                print(f"[SUBMIT ERROR] {e}")
                raise HTTPException(500, f"Failed to submit job: {e}")

            return {
                "message": "Job relaunched",
                "job_id": new_job_id
            }

        # ============================================================
        # REJECT KEEP
        # ============================================================
        elif decision == "reject_keep":
            
            # Mark version as rejected, keep original
            version.decision_status = StoryDecision.REJECTED

            await db.commit()

            return {"message": "Original version kept"}

        else:
            raise HTTPException(400, "Invalid decision")

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, str(e))


async def get_jobs_by_issue_keys(
    db: AsyncSession,
    issue_keys: List[str]
) -> Dict[str, Any]:
    """
    Get jobs for multiple issue keys.
    
    Returns latest version (approved or latest by date).
    
    Args:
        db: Database session
        issue_keys: List of Jira issue keys
        
    Returns:
        Dict mapping issue_key → job info
    """

    # ============================================================
    # Query jobs with relationships
    # ============================================================
    result = await db.execute(
        select(Job)
        .options(
            selectinload(Job.user_story),
            selectinload(Job.versions)
        )
        .join(Job.user_story)
        .where(UserStory.issue_key.in_(issue_keys))
    )

    jobs = result.scalars().all()

    # ============================================================
    # Map issue_key → list[jobs]
    # ============================================================
    job_map: Dict[str, List[Job]] = {}

    for job in jobs:
        key = job.user_story.issue_key
        job_map.setdefault(key, []).append(job)

    response = {}

    # ============================================================
    # For each issue key, get best version
    # ============================================================
    for issue_key in issue_keys:
        jobs_list = job_map.get(issue_key, [])

        if not jobs_list:
            response[issue_key] = None
            continue

        # Collect all versions from all jobs
        all_versions = []
        for job in jobs_list:
            all_versions.extend(job.versions)

        if not all_versions:
            response[issue_key] = None
            continue

        # Get approved version or latest by date
        approved_version = next(
            (v for v in all_versions if v.decision_status == StoryDecision.APPROVED),
            None
        )

        latest_version = max(
            all_versions,
            key=lambda v: v.created_at or v.iteration or 0
        )

        display_version = approved_version or latest_version

        # Get latest job for status
        latest_job = max(
            jobs_list,
            key=lambda j: j.started_at or 0
        )

        # ============================================================
        # Build response
        # ============================================================
        response[issue_key] = {
            "job_id": latest_job.id,
            "status": latest_job.status.value if latest_job.status else None,
            "phase": latest_job.phase.value if latest_job.phase else None,
            "iteration": display_version.iteration if display_version else 0,
            "improved_story": display_version.improved_story if display_version else None,
            "acceptance_criteria": (
                display_version.generated_acceptance_criteria
                if display_version else []
            ),
            "initial_score": display_version.initial_score if display_version else 0,
            "final_score": display_version.final_score if display_version else 0,
            "score_delta": (
                (display_version.final_score - display_version.initial_score)
                if display_version and display_version.initial_score is not None
                and display_version.final_score is not None
                else 0
            ),
            "decision_status": (
                display_version.decision_status.value
                if display_version and display_version.decision_status
                else "pending"
            ),
            "version_id": display_version.id if display_version else None,
            "has_new_version": len(all_versions) > 1,
            "versions_count": len(all_versions),
            "testability_score": (
                display_version.testability_score
                if display_version else None
            ),
            "is_testable": (
                display_version.is_testable
                if display_version else None
            ),
        }

    return response