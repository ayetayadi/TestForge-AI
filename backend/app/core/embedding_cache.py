import hashlib
import numpy as np
from typing import Optional
from collections import OrderedDict
from sentence_transformers import SentenceTransformer
from app.core.config import settings
from app.core.redis_client import get_redis
from app.core.model_manager import get_embedding_model
import asyncio

# =========================
# LRU CACHE (In-Memory)
# =========================

class LRUCache:
    """
    LRU (Least Recently Used) cache.
    """
    
    def __init__(self, max_size: int):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[np.ndarray]:
        if key in self.cache:
            self.cache.move_to_end(key)
            self.hits += 1
            return self.cache[key]
        self.misses += 1
        return None
    
    def set(self, key: str, value: np.ndarray):
        if key in self.cache:
            self.cache.move_to_end(key)
        else:
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)
        self.cache[key] = value
    
    def clear(self):
        self.cache.clear()
        self.hits = 0
        self.misses = 0
    
    def stats(self) -> dict:
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.1f}%",
            "memory_kb": len(self.cache) * settings.EMBEDDING_DIM * 4 / 1024,
        }


_memory_cache = LRUCache(max_size=settings.MEMORY_CACHE_SIZE)


# =========================
# CACHE KEY HELPERS
# =========================

def _cache_key(text: str) -> str:
    text_hash = hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16]
    return f"embed:{text_hash}"


def _serialize(embedding: np.ndarray) -> bytes:
    return embedding.astype(np.float32).tobytes()


def _deserialize(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32).copy()


# =========================
# MAIN EMBED FUNCTION
# =========================

async def embed(text: str) -> np.ndarray:
    """
    Generate embedding with two-layer caching (ASYNC).
    Utilise le modèle global préchargé.
    """
    if not text or not text.strip():
        return np.zeros(settings.EMBEDDING_DIM, dtype=np.float32)
    
    text = text.strip()
    key = _cache_key(text)
    
    # Layer 1: In-Memory (fastest)
    cached = _memory_cache.get(key)
    if cached is not None:
        return cached
    
    # Layer 2: Redis (async)
    redis = await get_redis()
    if redis is not None:
        try:
            data = await redis.get(key)
            if data:
                embedding = _deserialize(data)
                _memory_cache.set(key, embedding)
                return embedding
        except Exception:
            pass
    
    # Layer 3: Compute (slow - utilise le modèle global)
    model = get_embedding_model()  # ← Utilise le modèle préchargé !
    loop = asyncio.get_event_loop()
    embedding = await loop.run_in_executor(
        None,
        lambda: model.encode(text, normalize_embeddings=True)
    )
    embedding = np.array(embedding, dtype=np.float32)
    
    # Store in memory cache
    _memory_cache.set(key, embedding)
    
    # Store in Redis
    if redis is not None:
        try:
            await redis.setex(key, settings.REDIS_CACHE_TTL, _serialize(embedding))
        except Exception:
            pass
    
    return embedding


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Calcule la similarité cosinus entre deux vecteurs."""
    if a is None or b is None:
        return 0.0
    if len(a) == 0 or len(b) == 0:
        return 0.0
    
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    
    if norm_a == 0 or norm_b == 0:
        return 0.0

    sim = np.dot(a, b) / (norm_a * norm_b)
    
    if np.isnan(sim) or np.isinf(sim):
        return 0.0

    return float(sim)


# =========================
# SYNC WRAPPER (pour compatibilité)
# =========================

def embed_sync(text: str) -> np.ndarray:
    """Version synchrone pour code legacy."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, embed(text))
                return future.result()
        else:
            return loop.run_until_complete(embed(text))
    except RuntimeError:
        return asyncio.run(embed(text))