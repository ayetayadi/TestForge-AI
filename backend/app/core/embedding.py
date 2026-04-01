# app/core/embedding.py

import hashlib
import numpy as np
from sentence_transformers import SentenceTransformer
from app.core.config import settings
from app.core.redis_client import get_redis
from app.core.cache_memory import get_embedding_cache 

# =========================
# MODEL SINGLETON
# =========================
_model = None
_model_loading = False


def preload_embedding_model():
    global _model, _model_loading
    
    if _model is not None:
        print("[EMBED] Model already loaded")
        return
    
    if _model_loading:
        print("[EMBED] Model is currently loading...")
        return
    
    _model_loading = True
    try:
        print(f"[EMBED] Loading model: {settings.EMBEDDING_MODEL}")
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
        print("[EMBED] Model loaded successfully!")
    except Exception as e:
        print(f"[EMBED] Failed to load model: {e}")
        raise
    finally:
        _model_loading = False


def _get_model():
    global _model
    if _model is None:
        preload_embedding_model()
    return _model


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
def embed(text: str) -> np.ndarray:
    """
    Generate embedding with two-layer caching.
    Utilise le cache mémoire centralisé.
    """
    if not text or not text.strip():
        return np.zeros(settings.EMBEDDING_DIM, dtype=np.float32)
    
    text = text.strip()
    key = _cache_key(text)
    
    # Layer 1: In-Memory (centralized)
    memory_cache = get_embedding_cache()
    cached = memory_cache.get(key)
    if cached is not None:
        return cached
    
    # Layer 2: Redis (shared, if available)
    try:
        redis = get_redis()
        if redis is not None:
            try:
                data = redis.get(key)
                if data:
                    embedding = _deserialize(data)
                    memory_cache.set(key, embedding)
                    return embedding
            except Exception as e:
                print(f"[EMBED] Redis error: {e}")
    except Exception as e:
        print(f"[EMBED] Redis connection error: {e}")
    
    # Layer 3: Compute (slow)
    model = _get_model()
    embedding = model.encode(text, normalize_embeddings=True)
    embedding = np.array(embedding, dtype=np.float32)
    
    # Store in memory cache (always)
    memory_cache.set(key, embedding)
    
    # Store in Redis (if available)
    try:
        redis = get_redis()
        if redis is not None:
            try:
                redis.setex(key, settings.REDIS_CACHE_TTL, _serialize(embedding))
            except Exception:
                pass
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
# CACHE MANAGEMENT
# =========================
def get_cache_stats() -> dict:
    """Get statistics for both cache layers."""
    stats = {
        "memory": get_embedding_cache().stats(),
        "redis": {"available": False},
        "model_loaded": _model is not None,
    }
    
    try:
        redis = get_redis()
        if redis is not None:
            try:
                keys = redis.keys("embed:*")
                info = redis.info("memory")
                stats["redis"] = {
                    "available": True,
                    "items": len(keys) if keys else 0,
                    "memory_used": info.get("used_memory_human", "N/A"),
                    "ttl_seconds": settings.REDIS_CACHE_TTL,
                }
            except Exception as e:
                stats["redis"] = {"available": False, "error": str(e)}
    except Exception as e:
        stats["redis"] = {"available": False, "error": str(e)}
    
    return stats


def clear_all_cache():
    """Clear both cache layers."""
    get_embedding_cache().clear()
    print("[CACHE] Cleared embedding memory cache")
    
    try:
        redis = get_redis()
        if redis is not None:
            try:
                keys = redis.keys("embed:*")
                if keys:
                    redis.delete(*keys)
                    print(f"[CACHE] Cleared {len(keys)} Redis entries")
            except Exception as e:
                print(f"[CACHE] Redis clear error: {e}")
    except Exception as e:
        print(f"[CACHE] Redis connection error: {e}")