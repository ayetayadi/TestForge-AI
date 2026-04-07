from fastapi import Request
from fastapi.responses import StreamingResponse
import asyncio
import json

connections: dict[str, list[asyncio.Queue]] = {}
event_buffer: dict[str, list[dict]] = {}

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop):
    global _main_loop
    _main_loop = loop


def publish_event(job_id: str, event: str, data: dict):
    """Publish SSE event (synchrone, pour appels depuis threads)"""
    message = {
        "event": event,
        "data": data
    }

    # BUFFER AVEC LIMITE
    buffer = event_buffer.setdefault(job_id, [])
    buffer.append(message)

    if len(buffer) > 50:
        buffer.pop(0)

    if job_id not in connections:
        print(f"[SSE PUSH] job={job_id} event={event} (no listeners)")
        return

    if _main_loop is None:
        print("[SSE ERROR] main loop not set")
        return
    
    loop = _main_loop

    for queue in list(connections.get(job_id, [])):
        loop.call_soon_threadsafe(_safe_put, queue, message)

    print(f"[SSE PUSH] job={job_id} event={event}")


async def push_event(job_id: str, event: str, data: dict = None):
    """Push SSE event (async, pour appels depuis coroutines)"""
    message = {
        "event": event,
        "data": data or {}
    }

    # BUFFER AVEC LIMITE
    buffer = event_buffer.setdefault(job_id, [])
    buffer.append(message)

    if len(buffer) > 50:
        buffer.pop(0)

    # Push vers toutes les queues connectées
    queues = connections.get(job_id, [])
    
    if not queues:
        print(f"[SSE PUSH] job={job_id} event={event} (buffered, no listeners)")
        return

    for queue in list(queues):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            print("[SSE WARNING] Queue full → dropping event")

    print(f"[SSE PUSH] job={job_id} event={event}")


def _safe_put(queue: asyncio.Queue, message: dict):
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        print("[SSE WARNING] Queue full → dropping event")


async def event_generator(job_id: str, request: Request):
    queue = asyncio.Queue(maxsize=100)
    connections.setdefault(job_id, []).append(queue)

    print(f"[SSE CONNECT] job={job_id}")

    # REPLAY buffered events
    for msg in event_buffer.get(job_id, []):
        yield f"event: {msg['event']}\n"
        yield f"data: {json.dumps(msg['data'])}\n\n"

    try:
        while True:
            if await request.is_disconnected():
                break

            try:
                message = await asyncio.wait_for(queue.get(), timeout=15)

                yield f"event: {message['event']}\n"
                yield f"data: {json.dumps(message['data'])}\n\n"

                if message["event"] in ("completed", "failed"):
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
        
        # Ne pas supprimer le buffer immédiatement (pour replay si reconnexion)
        # if job_id in event_buffer:
        #     del event_buffer[job_id]


def sse_endpoint(request: Request, job_id: str):
    return StreamingResponse(
        event_generator(job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )