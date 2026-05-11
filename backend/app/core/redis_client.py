"""
Unified Redis client for the application.
Falls back gracefully when Redis is unavailable.
"""
import logging
import redis.asyncio as redis
from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_client = None
_redis_available = None


async def get_redis() -> redis.Redis | None:
    """
    Retourne le client Redis asynchrone.
    Utiliser dans tous les fichiers qui ont besoin de Redis.
    """
    global _redis_client, _redis_available
    
    # Si déjà marqué comme non disponible, ne pas réessayer
    if _redis_available is False:
        return None
    
    # Si pas encore de connexion, la créer
    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD or None,
                db=settings.REDIS_DB,
                decode_responses=False,  # False pour les embeddings (bytes), True pour le texte
                socket_timeout=2,
                socket_connect_timeout=2,
                retry_on_timeout=False,
            )
            await _redis_client.ping()
            _redis_available = True
            logger.info(f"[REDIS] Connected to {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        except Exception as e:
            logger.warning(f"[REDIS] Not available — falling back to in-memory: {e}")
            _redis_available = False
            _redis_client = None
    
    return _redis_client


async def reset_redis_connection():
    """Reset la connexion (utile si Redis redémarre)."""
    global _redis_client, _redis_available
    if _redis_client:
        await _redis_client.close()
    _redis_client = None
    _redis_available = None
    logger.info("[REDIS] Connection reset")

async def get_redis_with_decode() -> redis.Redis | None:
    """Version avec decode_responses=True pour le texte."""
    global _redis_client_decode, _redis_available
    
    if _redis_available is False:
        return None
    
    if _redis_client_decode is None:
        try:
            _redis_client_decode = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD or None,
                db=settings.REDIS_DB,
                decode_responses=True,
                socket_timeout=2,
                socket_connect_timeout=2,
            )
            await _redis_client_decode.ping()
        except Exception:
            return None
    
    return _redis_client_decode