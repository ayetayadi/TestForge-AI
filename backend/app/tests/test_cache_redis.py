# flush_redis.py
import asyncio
from app.core.redis_client import get_redis

async def flush():
    redis = await get_redis()
    if redis:
        await redis.flushall()
        print("✅ Redis cache vidé")

asyncio.run(flush())