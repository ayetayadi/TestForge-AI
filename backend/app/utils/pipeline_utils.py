from typing import Dict, Any
from app.streaming.sse_manager import publish_event

def add_trace(state: dict, step: str, data: dict) -> None:
    state.setdefault("trace", [])
    state["trace"].append({
        "step": step,
        "data": data
    })
    return state 

def safe_publish(state: Dict[str, Any], event: str, data: Dict[str, Any]) -> None:
    job_id = state.get("job_id")

    if not job_id:
        print("[PUBLISH ERROR] Missing job_id")
        return

    try:
        publish_event(job_id, event, data)
    except Exception as e:
        print(f"[PUBLISH ERROR] {e}")