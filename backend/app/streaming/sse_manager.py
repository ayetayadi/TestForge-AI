from fastapi import Request
from fastapi.responses import StreamingResponse
import asyncio
import json

from app.core.redis_client import get_redis
from app.core.cache_memory import get_sse_cache

# =========================
# SSE MANAGER
# =========================
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop):
    global _main_loop
    _main_loop = loop


def publish_event(job_id: str, event: str, data: dict):
    """Publie un événement pour un job."""
    message = {"event": event, "data": data}
    
    # Récupère le cache SSE
    sse_cache = get_sse_cache()
    
    # STOCKAGE REDIS
    try:
        redis = get_redis()
        if redis:
            redis.rpush(f"job:{job_id}:events", json.dumps(message))
            redis.ltrim(f"job:{job_id}:events", -200, -1)
            redis.expire(f"job:{job_id}:events", 3600)
    except Exception as e:
        print("[REDIS ERROR]", e)
    
    # LIVE SSE - utilise le cache mémoire centralisé
    if not sse_cache.has_connections(job_id):
        return
    
    loop = _main_loop
    if loop is None:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
    
    for queue in sse_cache.get_connections(job_id):
        loop.call_soon_threadsafe(_safe_put, queue, message)


def _safe_put(queue: asyncio.Queue, message: dict):
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        print("[SSE WARNING] Queue full → dropping event")


async def event_generator(job_id: str, request: Request):
    """Générateur d'événements SSE."""
    queue = asyncio.Queue(maxsize=100)
    
    # Utilise le cache centralisé
    sse_cache = get_sse_cache()
    sse_cache.add_connection(job_id, queue)
    
    # Récupère Redis
    redis = get_redis()
    
    try:
        # 1. REPLAY HISTORIQUE
        if redis:
            try:
                raw_events = redis.lrange(f"job:{job_id}:events", 0, -1)
                for raw in raw_events:
                    message = json.loads(raw)
                    yield f"event: {message['event']}\n"
                    yield f"data: {json.dumps(message['data'])}\n\n"
            except Exception as e:
                print("[REDIS REPLAY ERROR]", e)
        
        # 2. STREAM LIVE
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
        # Nettoie la connexion
        sse_cache.remove_connection(job_id, queue)


def sse_endpoint(request: Request, job_id: str):
    """Endpoint SSE."""
    return StreamingResponse(
        event_generator(job_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def get_sse_stats() -> dict:
    """Retourne les statistiques des connexions SSE."""
    sse_cache = get_sse_cache()
    return {
        "active_jobs": sse_cache.stats()["size"],
        "total_connections": sum(len(conns) for conns in sse_cache.get_all().values()),
        "cache_stats": sse_cache.stats(),
    }