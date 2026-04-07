from app.streaming.sse_manager import publish_event

def publish_ui_phase(state: dict, phase: str):
    job_id = state.get("job_id")
    state["ui_phase"] = phase
    if not job_id:
        return

    publish_event(job_id, "ui_phase", {
        "phase": phase,
        "iteration": state.get("iteration", 0),
        "jira_id": state.get("jira_id"),
    })