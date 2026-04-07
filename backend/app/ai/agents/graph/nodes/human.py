from app.core.database import SessionLocal
from app.repositories.story_final_repository import save_final_story
from app.utils.common.pipeline_utils import safe_publish
from app.services.jobs_service import store_job_result
from app.services.frontend_state_service import FrontendStateService

async def _persist(db, state, story, outcome):
    ok = await save_final_story(
        db=db,
        jira_id=state.get("jira_id"),
        final_story=story,
        outcome=outcome,
        state=state
    )

    if not ok:
        print("[PERSIST ERROR]", state.get("jira_id"))

async def persist_improved_node(state):

    async with SessionLocal() as db:
        story = state.get("improved_story") or state.get("raw_story")

        await _persist(db, state, story, "approved")

        safe_publish(state, "approved", {"story": story})

        state["final_story"] = story
        return state

async def persist_original_node(state):

    async with SessionLocal() as db:
        story = state.get("raw_story")

        await _persist(db, state, story, "reject_keep")

        safe_publish(state, "rejected", {})

        state["final_story"] = story
        return state

async def alert_user_node(state):

    async with SessionLocal() as db:
        story = state.get("raw_story")

        msg = (
            f"US non améliorable après {state.get('iteration', 0)} tentatives. "
            f"Delta max: {state.get('delta', 0):.2f}"
        )

        await _persist(db, state, story, "max_iter")

        safe_publish(state, "max_iter_reached", {"message": msg})

        state["final_story"] = story
        state["alert_message"] = msg

        return state
          
async def human_decision_node(state):
    state.setdefault("events", [])

    safe_publish(state, "awaiting_human", {
        "original_story": state.get("raw_story"),
        "improved_story": state.get("improved_story") or state.get("raw_story"),
        "score_before": state.get("initial_score", state.get("final_score")),
        "score_after": state.get("score_after", state.get("final_score")),
        "delta": state.get("delta", 0),
        "ac": state.get("acceptance_criteria") or state.get("existing_ac") or []
    })
    await FrontendStateService.update(state["job_id"], state)

    return state

async def persist_no_improvement_node(state):

    async with SessionLocal() as db:
        story = state.get("raw_story")

        await _persist(db, state, story, "no_improvement")

        safe_publish(state, "no_improvement", {})

        state["final_story"] = story
        return state