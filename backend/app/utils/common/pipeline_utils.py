import json

from app.streaming.sse_manager import publish_event

def add_trace(state: dict, step: str, data: dict) -> dict:
    trace = state.get("trace", []).copy()

    trace.append({
        "step": step,
        "data": data
    })

    return {
        **state,
        "trace": trace
    }

def safe_publish(state, event, data):
    if not isinstance(state, dict):
        print("[SAFE_PUBLISH ERROR] state is not dict")
        return

    job_id = state.get("job_id")

    if job_id:
        publish_event(job_id, event, data)
    
    print(f"\n[SSE EVENT] {event}")
    print(json.dumps(data, indent=2, ensure_ascii=False))
        