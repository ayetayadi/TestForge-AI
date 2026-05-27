"""
Centralized embedding model manager — singleton, loaded once at startup.
If the model is not cached locally and HuggingFace is unreachable the server
still starts; features that need embeddings fall back gracefully.
"""

import logging
from sentence_transformers import SentenceTransformer
from app.core.config import settings

logger = logging.getLogger(__name__)

_embedding_model = None


def preload_embedding_model():
    """Load the embedding model at startup. Fails silently on network error."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    try:
        logger.info("[EMBED] Loading model: %s", settings.EMBEDDING_MODEL)
        _embedding_model = SentenceTransformer(
            settings.EMBEDDING_MODEL,
            local_files_only=False,
        )
        logger.info("[EMBED] Model loaded successfully")
    except Exception as exc:
        logger.warning(
            "[EMBED] Could not load embedding model (%s) — "
            "semantic-search features will be unavailable. Error: %s",
            settings.EMBEDDING_MODEL,
            exc,
        )
    return _embedding_model


def get_embedding_model():
    """Return the preloaded singleton, or None if unavailable."""
    global _embedding_model
    if _embedding_model is None:
        preload_embedding_model()
    return _embedding_model
