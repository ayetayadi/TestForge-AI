from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user_story_final import UserStoryFinal
from app.models.user_story import UserStory
from app.models.enums import OutcomeEnum, HumanChoiceEnum, StatusEnum, SourceEnum
import json


async def save_final_story(
    db: AsyncSession,
    jira_id: str,
    final_story: str,
    outcome: str,
    state: dict
) -> bool:
    try:
        # Trouver la user story originale
        stmt = select(UserStory).where(UserStory.issue_key == jira_id)
        result = await db.execute(stmt)
        original_story = result.scalar_one_or_none()
        
        if not original_story:
            print(f"[FINAL STORY] User story {jira_id} not found")
            return False
        
        # Vérifier si une version finale existe déjà
        stmt = select(UserStoryFinal).where(
            UserStoryFinal.user_story_id == original_story.id
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        # Préparer les AC
        ac = state.get("acceptance_criteria", [])
        if isinstance(ac, str):
            try:
                ac = json.loads(ac)
            except:
                ac = [ac]
        
        # Préparer le statut en fonction de l'outcome
        if outcome == "failed":
            status = "failed"
        
        else:
            status = "completed"
        
        # Préparer human_choice
        human_choice = state.get("human_choice")
        if human_choice == "approve":
            human_choice_enum = "approve"
        elif human_choice == "reject_keep":
            human_choice_enum = "reject_keep"
        elif human_choice == "reject_relaunch":
            human_choice_enum = "reject_relaunch"
        else:
            human_choice_enum = None
        
        if outcome == "approved":
            outcome_enum = "approved"
        
        elif outcome == "reject_keep":
            outcome_enum = "reject_keep"
        
        elif outcome == "no_improvement":
            outcome_enum = "no_improvement"
        
        elif outcome == "max_iter":
            outcome_enum = "max_iter"
        
        elif outcome == "failed":
            outcome_enum = "failed"
        
        else:
            outcome_enum = "reject_keep"  # fallback safe
        
        if existing:
            # Mise à jour
            existing.improved_story = final_story
            existing.acceptance_criteria = ac
            existing.score_before = state.get("initial_score", 0)
            existing.score_after = state.get("score_after", state.get("final_score", 0))
            existing.delta = state.get("delta", 0)
            existing.iteration = state.get("iteration", 0)
            existing.outcome = outcome_enum
            existing.human_choice = human_choice_enum
            existing.status = status
            existing.job_id = state.get("job_id")
            existing.updated_at = datetime.utcnow()
        else:
            # Création
            final = UserStoryFinal(
                user_story_id=original_story.id,
                issue_key=original_story.issue_key,
                raw_story=state.get("raw_story", ""),
                improved_story=final_story,
                acceptance_criteria=ac,
                score_before=state.get("initial_score", 0),
                score_after=state.get("score_after", state.get("final_score", 0)),
                delta=state.get("delta", 0),
                iteration=state.get("iteration", 0),
                outcome=outcome_enum,
                human_choice=human_choice_enum,
                source="ai",
                status=status,
                job_id=state.get("job_id"),
                current_step=state.get("current_step"),
                events=state.get("events", []),
            )
            db.add(final)
        
        await db.commit()
        print(f"[FINAL STORY] Saved {jira_id} with outcome {outcome}")
        return True
        
    except Exception as e:
        print(f"[FINAL STORY ERROR] {e}")
        await db.rollback()
        return False


async def get_final_story_by_issue_key(
    db: AsyncSession,
    issue_key: str
) -> UserStoryFinal | None:
    """Récupère la version finale d'une story par son issue key"""
    try:
        stmt = select(UserStoryFinal).join(
            UserStory, UserStoryFinal.user_story_id == UserStory.id
        ).where(
            UserStory.issue_key == issue_key
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
        
    except Exception as e:
        print(f"[GET FINAL STORY ERROR] {e}")
        return None


async def get_all_final_stories(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0
) -> list[UserStoryFinal]:
    """Récupère toutes les versions finales"""
    try:
        stmt = select(UserStoryFinal).order_by(
            UserStoryFinal.created_at.desc()
        ).limit(limit).offset(offset)
        result = await db.execute(stmt)
        return result.scalars().all()
    except Exception as e:
        print(f"[GET FINAL STORIES ERROR] {e}")
        return []


async def get_final_stories_by_project(
    db: AsyncSession,
    project_id: str,
    limit: int = 100,
    offset: int = 0
) -> list[UserStoryFinal]:
    """Récupère les versions finales d'un projet"""
    try:
        stmt = select(UserStoryFinal).join(
            UserStory, UserStoryFinal.user_story_id == UserStory.id
        ).where(
            UserStory.jira_project_id == project_id
        ).order_by(
            UserStoryFinal.created_at.desc()
        ).limit(limit).offset(offset)
        result = await db.execute(stmt)
        return result.scalars().all()
    except Exception as e:
        print(f"[GET FINAL STORIES BY PROJECT ERROR] {e}")
        return []


async def get_finals_by_story_ids(
    db: AsyncSession, 
    story_ids: list[str] 
) -> list[UserStoryFinal]:
    """Récupère les versions finales par liste d'IDs de stories"""
    if not story_ids:
        return []

    try:
        stmt = select(UserStoryFinal).where(
            UserStoryFinal.user_story_id.in_(story_ids)
        )
        result = await db.execute(stmt)
        return result.scalars().all()
    except Exception as e:
        print(f"[GET FINALS BY STORY IDS ERROR] {e}")
        return []
 

# =========================
# AJOUTER CES FONCTIONS
# =========================

async def get_final_by_job_id(
    db: AsyncSession,
    job_id: str
) -> UserStoryFinal | None:
    """Récupère un résultat final par job_id (pour get_job_state)"""
    try:
        stmt = select(UserStoryFinal).where(
            UserStoryFinal.job_id == job_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as e:
        print(f"[GET FINAL BY JOB ID ERROR] {e}")
        return None


async def get_all_completed_jobs(
    db: AsyncSession,
    limit: int = 100
) -> list[UserStoryFinal]:
    """Récupère tous les jobs terminés (pour get_pending_jobs)"""
    try:
        stmt = select(UserStoryFinal).where(
            UserStoryFinal.status.in_(['completed', 'failed'])
        ).order_by(
            UserStoryFinal.updated_at.desc()
        ).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()
    except Exception as e:
        print(f"[GET ALL COMPLETED JOBS ERROR] {e}")
        return []


async def upsert_final_state(
    db: AsyncSession,
    jira_id: str,
    state: dict
) -> bool:
    try:
        # Trouver la user story
        stmt = select(UserStory).where(UserStory.issue_key == jira_id)
        result = await db.execute(stmt)
        original_story = result.scalar_one_or_none()
        
        if not original_story:
            print(f"[UPSERT FINAL] User story {jira_id} not found")
            return False
        
        # Vérifier si existe
        stmt = select(UserStoryFinal).where(
            UserStoryFinal.user_story_id == original_story.id
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        # Préparer les AC
        ac = state.get("acceptance_criteria", [])
        if isinstance(ac, str):
            try:
                ac = json.loads(ac)
            except:
                ac = [ac]
        
        # Déterminer le statut
        current_step = state.get("current_step", "")
        is_failed = state.get("llm_failed") or state.get("consecutive_llm_failures", 0) >= 2
        
        if current_step == "job_completed":
            status = "completed"
        elif is_failed:
            status = "failed"
        else:
            status = "processing"
        
        if existing:
            # Mise à jour
            existing.improved_story = state.get("improved_story")
            existing.acceptance_criteria = ac
            existing.score_before = state.get("initial_score", 0)
            existing.score_after = state.get("final_score", 0)
            existing.delta = state.get("delta", 0)
            existing.iteration = state.get("iteration", 0)
            existing.current_step = current_step
            existing.status = status
            existing.job_id = state.get("job_id")
            existing.events = state.get("events", [])
            existing.updated_at = datetime.utcnow()
        else:
            # Création
            new_final = UserStoryFinal(
                user_story_id=original_story.id,
                issue_key=original_story.issue_key,
                raw_story=state.get("raw_story", ""),
                improved_story=state.get("improved_story"),
                acceptance_criteria=ac,
                score_before=state.get("initial_score", 0),
                score_after=state.get("final_score", 0),
                delta=state.get("delta", 0),
                iteration=state.get("iteration", 0),
                outcome="processing",
                source="ai",
                status=status,
                current_step=current_step,
                job_id=state.get("job_id"),
                events=state.get("events", []),
            )
            db.add(new_final)
        
        await db.commit()
        return True
        
    except Exception as e:
        print(f"[UPSERT FINAL STATE ERROR] {e}")
        await db.rollback()
        return False
    