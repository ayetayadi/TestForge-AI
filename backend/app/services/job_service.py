from typing import Dict, List
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from unstructured_client import Any

from app.models.enums import StoryDecision
from app.models.job import Job
from app.models.user_story import UserStory
from app.repositories.job_repository import create_job
from app.repositories.user_story_repository import get_user_story_by_id
from app.repositories.user_story_version_repository import (
    get_version_by_id,
    reset_selected_versions,
    get_latest_version
)
from app.workers.asyncio_workers import submit_job


async def start_job(db: AsyncSession, user_story, use_cache: bool = True, reset: bool = False):
    user_story.decision_status = StoryDecision.PENDING
    await db.flush()
    
    latest = await get_latest_version(db, user_story.id)
    print(f"[START_JOB] {user_story.issue_key}")
    print(f"[START_JOB] latest_version exists: {latest is not None}")
    print(f"[START_JOB] use_cache param: {use_cache}")

    if reset:
        raw_story = user_story.description
        acceptance_criteria = user_story.acceptance_criteria or []
    else:
        raw_story = (
            latest.improved_story
            if latest else user_story.description
        )
    
        acceptance_criteria = (
            latest.acceptance_criteria
            if latest else user_story.acceptance_criteria or []
        )

    job_id = str(uuid.uuid4())

    await create_job(db, job_id, user_story.id)

    state = {
        "job_id": job_id,
        "jira_id": user_story.issue_key,
        "raw_story": raw_story,
        "acceptance_criteria": acceptance_criteria,
        "user_story_id": user_story.id,
        "iteration": 0,
        "use_cache": use_cache, 
    }
    print(f"[START_JOB] Final state use_cache: {state['use_cache']}")
    return job_id, state


async def apply_decision(
    db: AsyncSession,
    user_story_id: str,
    decision: str,
    version_id: str | None = None,
):
    try:
        user_story = await get_user_story_by_id(db, user_story_id)

        if not user_story:
            raise HTTPException(404, "User story not found")

        # =========================
        # APPROVE
        # =========================
        if decision == "approve":
        
            if not version_id:
                raise HTTPException(400, "version_id is required for approval")
        
            version = await get_version_by_id(db, version_id)
        
            if not version:
                raise HTTPException(404, "Version not found")
        
            if version.user_story_id != user_story_id:
                raise HTTPException(400, "Version does not belong to this story")
        
            await reset_selected_versions(db, user_story_id)
        
            version.is_selected = True
            user_story.decision_status = StoryDecision.APPROVED
        
            await db.commit()
        
            return {"message": "Approved"}

        # =========================
        # REJECT + RELAUNCH
        # =========================
        elif decision == "reject_relaunch":
            user_story.decision_status = StoryDecision.REJECTED_RELAUNCH
            await db.commit()
        
            new_job_id, state = await start_job(db, user_story, use_cache=False, reset=True)
            await db.commit()
            await submit_job(state)
        
            return {
                "message": "Relaunched",
                "job_id": new_job_id
            }

        # =========================
        # REJECT KEEP
        # =========================
        elif decision == "reject_keep":
            await reset_selected_versions(db, user_story_id)

            user_story.decision_status = StoryDecision.REJECTED_KEEP

            await db.commit()

            return {"message": "Original version kept"}

        else:
            raise HTTPException(400, "Invalid decision")

    except Exception:
        await db.rollback()
        raise

def _get_latest_version(job: Job):
    if not job.versions:
        return None
    return max(job.versions, key=lambda v: v.iteration)

async def get_jobs_by_issue_keys_service(
    db: AsyncSession,
    issue_keys: List[str]
) -> Dict[str, Any]:

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

    # mapping issue_key → job
    job_map = {
        job.user_story.issue_key: job
        for job in jobs
    }

    response = {}

    for issue_key in issue_keys:
        job = job_map.get(issue_key)

        if not job:
            response[issue_key] = None
            continue

        latest = _get_latest_version(job)
        story = job.user_story  # <-- AJOUTER CETTE LIGNE

        response[issue_key] = {
            "job_id": job.id,
            "status": job.status.value if job.status else None,  # <-- .value pour enum
            "phase": job.phase.value if job.phase else None,     # <-- .value pour enum
            "iteration": job.iteration,
            "improved_story": latest.improved_story if latest else None,
            "acceptance_criteria": latest.acceptance_criteria if latest else [],
            "initial_score": latest.initial_score if latest else 0,
            "final_score": latest.final_score if latest else 0,
            "score_delta": (
                (latest.final_score - latest.initial_score)
                if latest and latest.initial_score is not None and latest.final_score is not None
                else 0
            ),
            "decision_status": story.decision_status.value if story.decision_status else "pending",
            "version_id": latest.id if latest else None,
            "has_new_version": latest is not None and latest.iteration > 0
        }

    return response