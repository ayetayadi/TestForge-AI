from app.core.database import SessionLocal
from app.repositories.story_final_repository import save_final_story
from app.utils.common.pipeline_utils import safe_publish

def _persist(db, state, story, outcome):
    ok = save_final_story(
        db=db,
        jira_id=state.get("jira_id"),
        final_story=story,
        outcome=outcome,
        state=state
    )

    if not ok:
        print("[PERSIST ERROR]", state.get("jira_id"))

def persist_improved_node(state):
    db = SessionLocal()

    try:
        story = state.get("improved_story") or state.get("raw_story")

        _persist(db, state, story, "approved")

        safe_publish(state, "approved", {"story": story})

        state["final_story"] = story
        return state

    finally:
        db.close()

def persist_original_node(state):
    db = SessionLocal()

    try:
        story = state.get("raw_story")

        _persist(db, state, story, "reject_keep")

        safe_publish(state, "rejected", {})

        state["final_story"] = story
        return state

    finally:
        db.close()

def alert_user_node(state):
    db = SessionLocal()

    try:
        story = state.get("raw_story")

        msg = (
            f"US non améliorable après {state.get('iteration', 0)} tentatives. "
            f"Delta max: {state.get('delta', 0):.2f}"
        )

        _persist(db, state, story, "max_iter")

        safe_publish(state, "max_iter_reached", {"message": msg})

        state["final_story"] = story
        state["alert_message"] = msg

        return state

    finally:
        db.close()
        
def human_decision_node(state):

    safe_publish(state, "awaiting_human", {
        "original_story": state.get("raw_story"),
        "improved_story": state.get("improved_story") or state.get("raw_story"),
        "score_before": state.get("initial_score", state.get("final_score")),
        "score_after": state.get("score_after", state.get("final_score")),
        "delta": state.get("delta", 0),
        "ac": state.get("acceptance_criteria") or state.get("existing_ac") or []
    })

    return state