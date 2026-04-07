import hashlib
import numpy as np
from typing import Optional
from collections import OrderedDict
from sentence_transformers import SentenceTransformer
from app.core.config import settings


# =========================
# MODEL SINGLETON
# =========================
_model = None
_model_loading = False


def preload_embedding_model():
    """
    Précharge le modèle d'embedding.
    À appeler au démarrage de l'application.
    """
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
# LAYER 1: IN-MEMORY CACHE (per worker)
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
# LAYER 2: REDIS CACHE (shared across workers)
# =========================
_redis_client = None
_redis_available = None


def _get_redis():
    """Redis connection avec retry logic."""
    global _redis_client, _redis_available
    
    # Si déjà marqué comme non disponible, ne pas réessayer à chaque appel
    if _redis_available is False:
        return None
    
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD or None,
                db=settings.REDIS_DB,
                decode_responses=False,
                socket_timeout=1,           # Réduire le timeout
                socket_connect_timeout=1,   # Réduire le timeout
                retry_on_timeout=False,     # Ne pas retry automatiquement
            )
            _redis_client.ping()
            _redis_available = True
            print(f"[REDIS] Connected to {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        except Exception as e:
            print(f"[REDIS] Not available: {e}")
            _redis_available = False
            _redis_client = None
    
    return _redis_client


def reset_redis_connection():
    """Reset la connexion Redis (utile si Redis redémarre)."""
    global _redis_client, _redis_available
    _redis_client = None
    _redis_available = None
    print("[REDIS] Connection reset, will retry on next call")


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
    Optimisé pour la performance.
    """
    if not text or not text.strip():
        return np.zeros(settings.EMBEDDING_DIM, dtype=np.float32)
    
    text = text.strip()
    key = _cache_key(text)
    
    # Layer 1: In-Memory (fastest)
    cached = _memory_cache.get(key)
    if cached is not None:
        return cached
    
    # Layer 2: Redis (fast, shared) - avec timeout court
    redis = _get_redis()
    if redis is not None:
        try:
            data = redis.get(key)
            if data:
                embedding = _deserialize(data)
                _memory_cache.set(key, embedding)
                return embedding
        except Exception as e:
            # Ne pas bloquer si Redis échoue
            pass
    
    # Layer 3: Compute (slow)
    model = _get_model()
    embedding = model.encode(text, normalize_embeddings=True)
    embedding = np.array(embedding, dtype=np.float32)
    
    # Store in memory cache (toujours)
    _memory_cache.set(key, embedding)
    
    # Store in Redis (si disponible, en background)
    if redis is not None:
        try:
            redis.setex(key, settings.REDIS_CACHE_TTL, _serialize(embedding))
        except Exception:
            pass  # Ignore silently
    
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
        "memory": _memory_cache.stats(),
        "redis": {"available": False},
        "model_loaded": _model is not None,
    }
    
    redis = _get_redis()
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
    
    return stats


def clear_all_cache():
    """Clear both cache layers."""
    _memory_cache.clear()
    print("[CACHE] Cleared in-memory cache")
    
    redis = _get_redis()
    if redis is not None:
        try:
            keys = redis.keys("embed:*")
            if keys:
                redis.delete(*keys)
                print(f"[CACHE] Cleared {len(keys)} Redis entries")
        except Exception as e:
            print(f"[CACHE] Redis clear error: {e}")