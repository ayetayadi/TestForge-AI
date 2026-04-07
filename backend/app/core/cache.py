import json
import hashlib
from typing import Optional, Dict, Any

from app.core.redis_client import get_redis


class LLMCache:
    """Cache Redis pour les réponses LLM"""

    DEFAULT_TTL = 3600  # 1h

    @staticmethod
    def make_key(prefix: str, prompt: str) -> str:
        """Génère une clé stable"""
        hashed = hashlib.sha256(prompt.encode()).hexdigest()
        return f"llm:{prefix}:{hashed}"

    @staticmethod
    async def get(key: str) -> Optional[Dict[str, Any]]:
        redis = get_redis()

        try:
            data = await redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            print(f"[CACHE ERROR][GET] {e}")

        return None

    @staticmethod
    async def set(key: str, value: Dict[str, Any], ttl: int = DEFAULT_TTL):
        redis = get_redis()

        try:
            await redis.set(key, json.dumps(value), ex=ttl)
        except Exception as e:
            print(f"[CACHE ERROR][SET] {e}")