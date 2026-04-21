# app/core/llm_cache.py
import json
from typing import Any, Dict, Optional
from app.core.redis_client import get_redis_with_decode

class LLMCache:
    @staticmethod
    async def get(key: str) -> Optional[Dict[str, Any]]:
        redis = await get_redis_with_decode()
        if not redis:
            return None
        
        try:
            data = await redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            print(f"[CACHE ERROR][GET] {e}")
        
        return None
    
    @staticmethod
    async def set(key: str, value: Dict[str, Any], ttl: int = 3600):
        redis = await get_redis_with_decode()
        if not redis:
            return
        
        try:
            await redis.set(key, json.dumps(value), ex=ttl)
        except Exception as e:
            print(f"[CACHE ERROR][SET] {e}")