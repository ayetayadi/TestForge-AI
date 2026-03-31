import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from app.models.user_story import UserStory
from app.models.user_story_final import UserStoryFinal


async def save_final_story(db: AsyncSession, jira_id, final_story, outcome, state):
    try:
        result = await db.execute(
            select(UserStory).where(UserStory.issue_key == jira_id)
        )
        story = result.scalar_one_or_none()

        if not story:
            return False

        ac = state.get("acceptance_criteria", [])
        ac_json = ac if isinstance(ac, str) else json.dumps(ac)

        data = {
            "raw_story": story.description,
            "improved_story": final_story,
            "acceptance_criteria": ac_json,
            "score_before": state.get("initial_score"),
            "score_after": state.get("best_score") or state.get("score_after"),
            "delta": state.get("delta"),
            "iteration": state.get("iteration"),
            "outcome": outcome,
            "human_choice": state.get("human_choice"),
            "job_id": state.get("job_id"),
            "alert_message": state.get("alert_message"),
            "source": "ai"
        }

        result = await db.execute(
            select(UserStoryFinal).where(UserStoryFinal.user_story_id == story.id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
        else:
            final = UserStoryFinal(user_story_id=story.id, **data)
            db.add(final)

        await db.commit()
        return True

    except IntegrityError:
        await db.rollback()
        return False

    except SQLAlchemyError as e:
        await db.rollback()
        print("[DB ERROR save_final_story]", str(e))
        return False


async def get_final_by_story_id(db: AsyncSession, story_id: int):
    result = await db.execute(
        select(UserStoryFinal).where(UserStoryFinal.user_story_id == story_id)
    )
    return result.scalar_one_or_none()


async def get_finals_by_story_ids(db: AsyncSession, story_ids: list[int]):
    if not story_ids:
        return []

    result = await db.execute(
        select(UserStoryFinal).where(
            UserStoryFinal.user_story_id.in_(story_ids)
        )
    )
    return result.scalars().all()