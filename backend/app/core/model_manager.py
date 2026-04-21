"""
Gestionnaire centralisé du modèle d'embedding.
Singleton global pour éviter de recharger le modèle plusieurs fois.
"""

from sentence_transformers import SentenceTransformer
from app.core.config import settings

_embedding_model = None


def preload_embedding_model():
    """Précharge le modèle au démarrage de l'application."""
    global _embedding_model
    if _embedding_model is None:
        print(f"[EMBED] Loading model: {settings.EMBEDDING_MODEL}")
        _embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)
        print("[EMBED] Model loaded successfully!")
    return _embedding_model


def get_embedding_model():
    """Retourne le modèle préchargé (singleton global)."""
    global _embedding_model
    if _embedding_model is None:
        preload_embedding_model()
    return _embedding_model