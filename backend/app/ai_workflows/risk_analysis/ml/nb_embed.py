"""
Modèles ML + SentenceTransformers pour Risk Analysis.

- NaiveBayesEmbedModel        : conteneur utilisé avec LinearSVC (CalibratedClassifierCV)
- GaussianNBEmbedModel        : Naive Bayes gaussien réel, adapté aux embeddings continus
- GradientBoostingEmbedModel  : XGBoost (XGBClassifier), boosting par arbres

Les trois prédisent P (1-5) et I (1-5) à partir du texte d'une user story.
"""

import logging
import os

import joblib
import numpy as np

from .config import EMBED_MODEL_NAME, ML_CONFIDENCE_THRESHOLD
from .models import MLPrediction

logger = logging.getLogger(__name__)

MODEL_PATH     = "app/ai_workflows/risk_analysis/ml/results/risk_nb_embed.txt"
MODEL_PATH_GNB = "app/ai_workflows/risk_analysis/ml/results/risk_gnb_embed.txt"
MODEL_PATH_GBM = "app/ai_workflows/risk_analysis/ml/results/risk_gbm_embed.txt"
MODEL_PATH_KNN = "app/ai_workflows/risk_analysis/ml/results/risk_knn_embed.txt"
MODEL_PATH_DT  = "app/ai_workflows/risk_analysis/ml/results/risk_dt_embed.txt"

# Singleton : l'encodeur est chargé une seule fois par processus
_encoder = None


def _get_encoder(model_name: str):
    global _encoder
    if _encoder is None:
        try:
            from app.core.model_manager import get_embedding_model
            _encoder = get_embedding_model()
            logger.info("SentenceTransformer récupéré depuis model_manager (singleton global)")
        except Exception:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Chargement SentenceTransformer standalone : {model_name}")
            _encoder = SentenceTransformer(model_name)
    return _encoder


def _encode(texts: list, model_name: str) -> np.ndarray:
    enc = _get_encoder(model_name)
    return enc.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 50,
        batch_size=64,
    )


class NaiveBayesEmbedModel:
    """
    GaussianNB entraîné sur des embeddings SentenceTransformer.
    Prédit P (1-5) et I (1-5) indépendamment.
    """

    def __init__(self, embed_model_name: str = EMBED_MODEL_NAME):
        self.embed_model_name = embed_model_name
        self.model_P = None
        self.model_I = None
        self.is_trained = False

    def encode(self, texts: list) -> np.ndarray:
        return _encode(texts, self.embed_model_name)

    def predict(self, text: str) -> MLPrediction:
        X = self.encode([text])
    
        p_class = int(self.model_P.predict(X)[0])
        p_proba = float(np.max(self.model_P.predict_proba(X)[0]))
    
        i_class = int(self.model_I.predict(X)[0])
        i_proba = float(np.max(self.model_I.predict_proba(X)[0]))
    
        n_classes_P = len(self.model_P.classes_)
        if n_classes_P == 3:
            # Mapping 3→5
            _expand = {1: 2, 2: 3, 3: 5}
            p = _expand.get(p_class, p_class)
            i = _expand.get(i_class, i_class)
        else:
            # 5 classes → utiliser directement
            p = p_class
            i = i_class
    
        confidence = round((p_proba + i_proba) / 2, 3)
        source = "nb_embed" if confidence >= ML_CONFIDENCE_THRESHOLD else "nb_embed_low_conf"
    
        return MLPrediction(probability=p, impact=i, confidence=confidence, source=source)

    def save(self, path: str = MODEL_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({
            "embed_model_name": self.embed_model_name,
            "model_P": self.model_P,
            "model_I": self.model_I,
        }, path)
        logger.info(f"Modèle sauvegardé : {path}")

    def load(self, path: str = MODEL_PATH) -> bool:
        if not os.path.exists(path):
            logger.warning(f"Modèle introuvable : {path}")
            return False
        data = joblib.load(path)
        self.embed_model_name = data["embed_model_name"]
        self.model_P = data["model_P"]
        self.model_I = data["model_I"]
        self.is_trained = True
        logger.info(f"Modèle chargé : {path}")
        return True


# ── Naive Bayes gaussien réel ──────────────────────────────────────────────────


class GaussianNBEmbedModel:
    """
    GaussianNB entraîné sur des embeddings SentenceTransformer.
    Contrairement à NaiveBayesEmbedModel (qui stocke un LinearSVC),
    cette classe utilise un vrai GaussianNB adapté aux features continues.
    Prédit P (1-5) et I (1-5) indépendamment.
    """

    def __init__(self, embed_model_name: str = EMBED_MODEL_NAME):
        self.embed_model_name = embed_model_name
        self.model_P = None  # GaussianNB ou GridSearchCV wrappé
        self.model_I = None
        self.is_trained = False

    def encode(self, texts: list) -> np.ndarray:
        return _encode(texts, self.embed_model_name)

    def predict(self, text: str) -> MLPrediction:
        X = self.encode([text])

        p_class = int(self.model_P.predict(X)[0])
        p_proba = float(np.max(self.model_P.predict_proba(X)[0]))

        i_class = int(self.model_I.predict(X)[0])
        i_proba = float(np.max(self.model_I.predict_proba(X)[0]))

        confidence = round((p_proba + i_proba) / 2, 3)
        source = "gnb_embed" if confidence >= ML_CONFIDENCE_THRESHOLD else "gnb_embed_low_conf"

        return MLPrediction(
            probability=p_class,
            impact=i_class,
            confidence=confidence,
            source=source,
        )

    def save(self, path: str = MODEL_PATH_GNB):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({
            "embed_model_name": self.embed_model_name,
            "model_P": self.model_P,
            "model_I": self.model_I,
        }, path)
        logger.info(f"Modèle GNB sauvegardé : {path}")

    def load(self, path: str = MODEL_PATH_GNB) -> bool:
        if not os.path.exists(path):
            logger.warning(f"Modèle GNB introuvable : {path}")
            return False
        data = joblib.load(path)
        self.embed_model_name = data["embed_model_name"]
        self.model_P = data["model_P"]
        self.model_I = data["model_I"]
        self.is_trained = True
        logger.info(f"Modèle GNB chargé : {path}")
        return True


# ── Gradient Boosting (HistGradientBoosting) ──────────────────────────────────


class GradientBoostingEmbedModel:
    """
    XGBClassifier entraîné sur des embeddings SentenceTransformer.
    Boosting par arbres (gradient boosting), robuste sur des features
    continues à haute dimension (384 dims).
    Prédit P (1-5) et I (1-5) indépendamment.
    """

    def __init__(self, embed_model_name: str = EMBED_MODEL_NAME):
        self.embed_model_name = embed_model_name
        self.model_P = None
        self.model_I = None
        self.is_trained = False

    def encode(self, texts: list) -> np.ndarray:
        return _encode(texts, self.embed_model_name)

    def predict(self, text: str) -> MLPrediction:
        X = self.encode([text])

        # XGBoost prédit des labels 0-indexés [0-4] → ramener à [1-5]
        p_class = int(self.model_P.predict(X)[0]) + 1
        p_proba = float(np.max(self.model_P.predict_proba(X)[0]))

        i_class = int(self.model_I.predict(X)[0]) + 1
        i_proba = float(np.max(self.model_I.predict_proba(X)[0]))

        confidence = round((p_proba + i_proba) / 2, 3)
        source = "gbm_embed" if confidence >= ML_CONFIDENCE_THRESHOLD else "gbm_embed_low_conf"

        return MLPrediction(
            probability=p_class,
            impact=i_class,
            confidence=confidence,
            source=source,
        )

    def save(self, path: str = MODEL_PATH_GBM):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({
            "embed_model_name": self.embed_model_name,
            "model_P": self.model_P,
            "model_I": self.model_I,
        }, path)
        logger.info(f"Modèle GBM sauvegardé : {path}")

    def load(self, path: str = MODEL_PATH_GBM) -> bool:
        if not os.path.exists(path):
            logger.warning(f"Modèle GBM introuvable : {path}")
            return False
        data = joblib.load(path)
        self.embed_model_name = data["embed_model_name"]
        self.model_P = data["model_P"]
        self.model_I = data["model_I"]
        self.is_trained = True
        logger.info(f"Modèle GBM chargé : {path}")
        return True


# ── K-Nearest Neighbors ────────────────────────────────────────────────────────


class KNNEmbedModel:
    """
    KNeighborsClassifier entraîné sur des embeddings SentenceTransformer.
    Métrique cosine (naturelle pour des embeddings normalisés L2).
    n_neighbors et weights tunés via GridSearchCV.
    Prédit P (1-5) et I (1-5) indépendamment.
    """

    def __init__(self, embed_model_name: str = EMBED_MODEL_NAME):
        self.embed_model_name = embed_model_name
        self.model_P = None
        self.model_I = None
        self.is_trained = False

    def encode(self, texts: list) -> np.ndarray:
        return _encode(texts, self.embed_model_name)

    def predict(self, text: str) -> MLPrediction:
        X = self.encode([text])

        p_class = int(self.model_P.predict(X)[0])
        p_proba = float(np.max(self.model_P.predict_proba(X)[0]))

        i_class = int(self.model_I.predict(X)[0])
        i_proba = float(np.max(self.model_I.predict_proba(X)[0]))

        confidence = round((p_proba + i_proba) / 2, 3)
        source = "knn_embed" if confidence >= ML_CONFIDENCE_THRESHOLD else "knn_embed_low_conf"

        return MLPrediction(
            probability=p_class,
            impact=i_class,
            confidence=confidence,
            source=source,
        )

    def save(self, path: str = MODEL_PATH_KNN):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({
            "embed_model_name": self.embed_model_name,
            "model_P": self.model_P,
            "model_I": self.model_I,
        }, path)
        logger.info(f"Modèle KNN sauvegardé : {path}")

    def load(self, path: str = MODEL_PATH_KNN) -> bool:
        if not os.path.exists(path):
            logger.warning(f"Modèle KNN introuvable : {path}")
            return False
        data = joblib.load(path)
        self.embed_model_name = data["embed_model_name"]
        self.model_P = data["model_P"]
        self.model_I = data["model_I"]
        self.is_trained = True
        logger.info(f"Modèle KNN chargé : {path}")
        return True


# ── Decision Tree ──────────────────────────────────────────────────────────────


class DecisionTreeEmbedModel:
    """
    DecisionTreeClassifier entraîné sur des embeddings SentenceTransformer.
    max_depth, min_samples_split, min_samples_leaf et criterion tunés via GridSearchCV.
    Prédit P (1-5) et I (1-5) indépendamment.
    """

    def __init__(self, embed_model_name: str = EMBED_MODEL_NAME):
        self.embed_model_name = embed_model_name
        self.model_P = None
        self.model_I = None
        self.is_trained = False

    def encode(self, texts: list) -> np.ndarray:
        return _encode(texts, self.embed_model_name)

    def predict(self, text: str) -> MLPrediction:
        X = self.encode([text])

        p_class = int(self.model_P.predict(X)[0])
        p_proba = float(np.max(self.model_P.predict_proba(X)[0]))

        i_class = int(self.model_I.predict(X)[0])
        i_proba = float(np.max(self.model_I.predict_proba(X)[0]))

        confidence = round((p_proba + i_proba) / 2, 3)
        source = "dt_embed" if confidence >= ML_CONFIDENCE_THRESHOLD else "dt_embed_low_conf"

        return MLPrediction(
            probability=p_class,
            impact=i_class,
            confidence=confidence,
            source=source,
        )

    def save(self, path: str = MODEL_PATH_DT):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump({
            "embed_model_name": self.embed_model_name,
            "model_P": self.model_P,
            "model_I": self.model_I,
        }, path)
        logger.info(f"Modèle DT sauvegardé : {path}")

    def load(self, path: str = MODEL_PATH_DT) -> bool:
        if not os.path.exists(path):
            logger.warning(f"Modèle DT introuvable : {path}")
            return False
        data = joblib.load(path)
        self.embed_model_name = data["embed_model_name"]
        self.model_P = data["model_P"]
        self.model_I = data["model_I"]
        self.is_trained = True
        logger.info(f"Modèle DT chargé : {path}")
        return True
