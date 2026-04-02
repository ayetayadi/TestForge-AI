from fastapi import Request
from fastapi.responses import StreamingResponse
import asyncio
import json
 
connections: dict[str, list[asyncio.Queue]] = {}

_main_loop: asyncio.AbstractEventLoop | None = None
 
 
def set_main_loop(loop: asyncio.AbstractEventLoop):
    """Appeler au demarrage de FastAPI : set_main_loop(asyncio.get_event_loop())"""
    global _main_loop
    _main_loop = loop
 
 
def publish_event(job_id: str, event: str, data: dict):
    if job_id not in connections:
        return
 
    message = {"event": event, "data": data}
 
    loop = _main_loop
    if loop is None:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
 
    for queue in list(connections.get(job_id, [])):
        loop.call_soon_threadsafe(_safe_put, queue, message)
 
 
def _safe_put(queue: asyncio.Queue, message: dict):
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        print("[SSE WARNING] Queue full → dropping event") 
 
async def event_generator(job_id: str, request: Request):
    queue = asyncio.Queue(maxsize=100)
    connections.setdefault(job_id, []).append(queue)

    try:
        while True:

            if await request.is_disconnected():
                break

            try:
                message = await asyncio.wait_for(queue.get(), timeout=15)

                yield f"event: {message['event']}\n"
                yield f"data: {json.dumps(message['data'])}\n\n"

                if message["event"] in ("approved", "rejected", "max_iter_reached"):
                    break

            except asyncio.TimeoutError:
                yield "event: ping\ndata: {}\n\n"

    finally:
        if job_id in connections:
            try:
                connections[job_id].remove(queue)
            except ValueError:
                pass

            if not connections[job_id]:
                del connections[job_id]

def sse_endpoint(request: Request, job_id: str):
    return StreamingResponse(
        event_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
 