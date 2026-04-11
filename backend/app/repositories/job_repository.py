from sqlalchemy.orm import selectinload
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.enums import JobStatus
from app.models.job import Job
from app.models.user_story import UserStory

async def create_job(db: AsyncSession, job_id: str, user_story_id: str):
    # Créer le job
    job = Job(
        id=job_id,
        user_story_id=user_story_id
    )
    db.add(job)
    await db.flush()
    
    return job

async def get_job_by_id(db: AsyncSession, job_id: str):
    """Get job with user_story and versions loaded"""
    result = await db.execute(
        select(Job)
        .options(
            selectinload(Job.user_story),
            selectinload(Job.versions)
        )
        .where(Job.id == job_id)
    )
    return result.scalar_one_or_none()

async def get_active_jobs(db: AsyncSession):
    result = await db.execute(
        select(Job).where(
            Job.status == JobStatus.PROCESSING
        )
    )
    return result.scalars().all()