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
    version_id = state.get("version_id")

    if not version_id:
        print("[PUBLISH ERROR] Missing version_id")
        return

    try:
        publish_event(version_id, event, data)
    except Exception as e:
        print(f"[PUBLISH ERROR] {e}")