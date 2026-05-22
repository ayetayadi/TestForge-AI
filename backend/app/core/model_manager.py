"""
Gestionnaire centralisé du modèle d'embedding.
Singleton global pour éviter de recharger le modèle plusieurs fois.
"""

from sentence_transformers import SentenceTransformer
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

_embedding_model = None
_nlp_fr = None
_nlp_en = None


def preload_embedding_model():
    """Précharge le modèle au démarrage de l'application."""
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"[EMBED] Loading model: {settings.EMBEDDING_MODEL}")
        _embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)
        logger.info("[EMBED] Model loaded successfully!")
    return _embedding_model


def get_embedding_model():
    """Retourne le modèle préchargé (singleton global)."""
    global _embedding_model
    if _embedding_model is None:
        preload_embedding_model()
    return _embedding_model


def preload_spacy_models():
    """Précharge les modèles spaCy FR et EN au démarrage."""
    global _nlp_fr, _nlp_en
    import spacy
    
    if _nlp_fr is None:
        logger.info("[NLP] Loading spaCy model: fr_core_news_sm")
        _nlp_fr = spacy.load("fr_core_news_sm")
        logger.info("[NLP] spaCy FR model loaded!")
    
    if _nlp_en is None:
        logger.info("[NLP] Loading spaCy model: en_core_web_sm")
        _nlp_en = spacy.load("en_core_web_sm")
        logger.info("[NLP] spaCy EN model loaded!")
    
    return _nlp_fr, _nlp_en


def get_spacy_model(lang: str):
    """Retourne le modèle spaCy préchargé pour la langue demandée."""
    global _nlp_fr, _nlp_en
    
    if lang == "fr":
        if _nlp_fr is None:
            preload_spacy_models()
        return _nlp_fr
    else:
        if _nlp_en is None:
            preload_spacy_models()
        return _nlp_en