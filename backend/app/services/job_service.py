from typing import Dict, List, Any
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


async def start_job(db: AsyncSession, user_story, use_cache: bool = True, reset: bool = False):
    
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
            latest.generated_acceptance_criteria
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

        if decision in ("approve", "reject_relaunch", "reject_keep"):
            if not version_id:
                raise HTTPException(400, "version_id is required")

        version = await get_version_by_id(db, version_id) if version_id else None

        if not version:
            raise HTTPException(404, "Version not found")

        if version.user_story_id != user_story_id:
            raise HTTPException(400, "Version does not belong to this story")

        # =========================
        # APPROVE
        # =========================
        if decision == "approve":

            versions = await get_versions_by_story_id(db, user_story_id)

            for v in versions:
                if v.id != version.id:
                    v.decision_status = StoryDecision.REJECTED

            version.decision_status = StoryDecision.APPROVED

            await db.commit()

            return {"message": "Approved"}

        # =========================
        # REJECT + RELAUNCH
        # =========================
        elif decision == "reject_relaunch":

            version.decision_status = StoryDecision.REJECTED

            new_job_id, state = await start_job(
                db,
                user_story,
                use_cache=False,
                reset=True
            )

            await db.commit()

            try:
                await submit_job(state)
            except Exception as e:
                print(f"[SUBMIT ERROR] {e}")

            return {
                "message": "Relaunched",
                "job_id": new_job_id
            }

        # =========================
        # REJECT KEEP
        # =========================
        elif decision == "reject_keep":

            version.decision_status = StoryDecision.REJECTED

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
    return max(job.versions, key=lambda v: (v.iteration or 0))

async def get_jobs_by_issue_keys(
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

    # =========================
    # mapping issue_key → list[jobs]
    # =========================
    job_map: Dict[str, List[Job]] = {}

    for job in jobs:
        key = job.user_story.issue_key
        job_map.setdefault(key, []).append(job)

    response = {}

    for issue_key in issue_keys:
        jobs_list = job_map.get(issue_key, [])

        if not jobs_list:
            response[issue_key] = None
            continue

        # =========================
        # collect ALL versions
        # =========================
        all_versions = []
        for job in jobs_list:
            all_versions.extend(job.versions)

        if not all_versions:
            response[issue_key] = None
            continue

        # =========================
        # latest version (global)
        # =========================
        latest = max(
            all_versions,
            key=lambda v: v.created_at or v.iteration or 0
        )

        # =========================
        # selected version (approved)
        # =========================
        selected = next(
            (v for v in all_versions if v.decision_status == StoryDecision.APPROVED),
            None
        )

        display = selected or latest

        # =========================
        # latest job (pour status UI)
        # =========================
        latest_job = max(
            jobs_list,
            key=lambda j: j.started_at or 0
        )

        # =========================
        # response
        # =========================
        response[issue_key] = {
            "job_id": latest_job.id,
            "status": latest_job.status.value if latest_job.status else None,
            "phase": latest_job.phase.value if latest_job.phase else None,
            "iteration": display.iteration if display else 0,
            "improved_story": display.improved_story if display else None,
            "acceptance_criteria": display.generated_acceptance_criteria if display else [],
            "initial_score": display.initial_score if display else 0,
            "final_score": display.final_score if display else 0,
            "score_delta": (
                (display.final_score - display.initial_score)
                if display and display.initial_score is not None and display.final_score is not None
                else 0
            ),
            "decision_status": (
                display.decision_status.value
                if display and display.decision_status
                else "pending"
            ),
            "version_id": display.id if display else None,
            "has_new_version": len(all_versions) > 1,
            "versions_count": len(all_versions)
        }

    return response