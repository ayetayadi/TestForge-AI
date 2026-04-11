from typing import List, Dict, Optional
from sqlalchemy import select
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_story import UserStory
from app.repositories.user_story_repository import (
    get_user_stories_by_project_id,
    count_user_stories_by_project,
)
from app.repositories.project_repository import get_project_by_id
from app.services.job_service import start_job
from app.workers.asyncio_workers import submit_job


def validate_input(issue_keys, project_id):
    if not issue_keys and not project_id:
        raise ValueError("Provide issue_keys or project_id")

    if issue_keys and project_id:
        raise ValueError("Use either issue_keys OR project_id")


async def validate_project_exists(db: AsyncSession, project_id: str):
    project = await get_project_by_id(db, project_id)
    if not project:
        raise ValueError("Project not found")


async def validate_project_has_stories(db: AsyncSession, project_id: str):
    count = await count_user_stories_by_project(db, project_id)
    if count == 0:
        raise ValueError("Project has no user stories")


async def run_pipeline(
    db: AsyncSession,
    issue_keys: Optional[List[str]],
    project_id: Optional[str],
) -> Dict[str, object]:

    validate_input(issue_keys, project_id)

    # normalize
    issue_keys = list(dict.fromkeys(issue_keys)) if issue_keys else None

    # LOAD STORIES
    if issue_keys:
        result = await db.execute(
            select(UserStory).where(UserStory.issue_key.in_(issue_keys))
        )
        user_stories = result.scalars().all()

        if len(user_stories) != len(issue_keys):
            raise ValueError("Some stories not found")

    else:
        await validate_project_exists(db, project_id)
        await validate_project_has_stories(db, project_id)

        user_stories = await get_user_stories_by_project_id(db, project_id)

    if not user_stories:
        raise ValueError("No stories found")

    if len(user_stories) > 100:
        raise ValueError("Too many user stories")

    jobs = []
    skipped = []
    states = []

    try:
        for us in user_stories:
            try:
                job_id, state = await start_job(db, us)
            except ValueError as e:
                skipped.append({
                    "issue_key": us.issue_key,
                    "reason": str(e)
                })
                continue

            states.append(state)

            jobs.append({
                "job_id": job_id,
                "issue_key": us.issue_key,
            })

        await db.commit()

    except Exception:
        await db.rollback()
        raise

    # async execution (hors transaction)
    await asyncio.gather(*[
        submit_job(state) for state in states
    ], return_exceptions=True)

    return {
        "total_requests": len(user_stories),
        "total_jobs": len(jobs),
        "skipped": skipped,
        "jobs": jobs,
    }