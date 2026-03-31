import json
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from app.models.user_story import UserStory
from app.models.user_story_final import UserStoryFinal


def save_final_story(db: Session, jira_id, final_story, outcome, state):

    try:
        story = db.query(UserStory).filter_by(issue_key=jira_id).first()

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

        existing = db.query(UserStoryFinal).filter_by(user_story_id=story.id).first()

        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
        else:
            final = UserStoryFinal(user_story_id=story.id, **data)
            db.add(final)

        db.commit()
        return True

    except IntegrityError:
        db.rollback()

        existing = db.query(UserStoryFinal).filter_by(user_story_id=story.id).first()

        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            db.commit()
            return True

        return False

    except SQLAlchemyError as e:
        db.rollback()
        print("[DB ERROR save_final_story]", str(e))
        return False
    


def get_final_by_story_id(db: Session, story_id: int):
    return db.query(UserStoryFinal).filter_by(user_story_id=story_id).first()
 
 
def get_finals_by_story_ids(db: Session, story_ids: list[int]):
    if not story_ids:
        return []
    return db.query(UserStoryFinal).filter(
        UserStoryFinal.user_story_id.in_(story_ids)
    ).all()