"""
ML Model — Prédit P (1-5) et I (1-5) à partir du texte US+AC.

Deux modes :
  - train() : entraîne le modèle sur un dataset annoté
  - predict() : prédit P et I pour une nouvelle US

Modèle : TF-IDF + XGBoost (classification multi-classe)
"""

import logging
import os
from typing import Tuple, Optional
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from xgboost import XGBClassifier

from .config import (
    TFIDF_MAX_FEATURES,
    ML_CONFIDENCE_THRESHOLD,
)
from .models import MLPrediction

logger = logging.getLogger(__name__)

# Chemin où sauvegarder le modèle entraîné
MODEL_PATH = "models/risk_ml_model.pkl"


class RiskMLModel:
    """
    Modèle ML pour prédire la Probabilité (1-5) et l'Impact (1-5)
    d'une User Story à partir de son texte.
    """

    def __init__(self):
        self.vectorizer: Optional[TfidfVectorizer] = None
        self.model_P: Optional[XGBClassifier] = None  # Prédit la Probabilité
        self.model_I: Optional[XGBClassifier] = None  # Prédit l'Impact
        self.is_trained = False

    # ============================================================
    # ENTRAÎNEMENT
    # ============================================================

    def train(
        self,
        texts: list[str],         # Liste des US+AC combinées
        labels_P: list[int],      # Vraies valeurs P (1-5)
        labels_I: list[int],      # Vraies valeurs I (1-5)
        save: bool = True,
    ) -> dict:
        """
        Entraîne le modèle sur un dataset annoté.

        Args:
            texts : liste de textes combinés (US + AC)
            labels_P : liste des vrais P (1, 2, 3, 4, ou 5)
            labels_I : liste des vrais I (1, 2, 3, 4, ou 5)
            save : si True, sauvegarde le modèle sur disque

        Returns:
            dict avec les métriques d'entraînement

        Example:
            model.train(
                texts=["payer par carte 3DS", "consulter profil admin"],
                labels_P=[4, 1],
                labels_I=[5, 2]
            )
        """
        logger.info(f"Entraînement du modèle sur {len(texts)} exemples...")

        # Étape 1 : Vectoriser le texte avec TF-IDF
        # TF-IDF transforme chaque texte en un vecteur de 500 nombres
        self.vectorizer = TfidfVectorizer(max_features=TFIDF_MAX_FEATURES)
        X = self.vectorizer.fit_transform(texts)

        # Étape 2 : Entraîner un modèle pour P
        self.model_P = XGBClassifier(
            n_estimators=100,       # 100 arbres de décision
            max_depth=5,            # Profondeur max de chaque arbre
            learning_rate=0.1,      # Vitesse d'apprentissage
            random_state=42,        # Pour des résultats reproductibles
        )
        self.model_P.fit(X, labels_P)

        # Étape 3 : Entraîner un modèle pour I
        self.model_I = XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=42,
        )
        self.model_I.fit(X, labels_I)

        self.is_trained = True

        # Étape 4 : Sauvegarder le modèle
        if save:
            self.save()

        # Calculer l'accuracy sur les données d'entraînement
        acc_P = self.model_P.score(X, labels_P)
        acc_I = self.model_I.score(X, labels_I)

        logger.info(f"Entraînement terminé. Accuracy P: {acc_P:.2f}, Accuracy I: {acc_I:.2f}")

        return {
            "accuracy_P": acc_P,
            "accuracy_I": acc_I,
            "n_samples": len(texts),
            "n_features": TFIDF_MAX_FEATURES,
        }

    # ============================================================
    # PRÉDICTION
    # ============================================================

    def predict(self, text: str) -> MLPrediction:
        """
        Prédit P et I pour une nouvelle User Story.

        Args:
            text : texte combiné de l'US + AC

        Returns:
            MLPrediction avec P, I, confiance, source

        Example:
            model.predict("payer par carte avec authentification 3DS")
            → MLPrediction(probability=4, impact=5, confidence=0.85, source="ml")
        """
        if not self.is_trained:
            # Essayer de charger un modèle sauvegardé
            if not self.load():
                raise RuntimeError(
                    "Aucun modèle entraîné. Exécutez train() d'abord ou fournissez un fichier modèle."
                )

        # Étape 1 : Vectoriser le texte
        X = self.vectorizer.transform([text])

        # Étape 2 : Prédire P
        p = int(self.model_P.predict(X)[0])+1
        # Probabilité de la classe prédite = confiance
        p_confidence = float(np.max(self.model_P.predict_proba(X)[0]))

        # Étape 3 : Prédire I
        i = int(self.model_I.predict(X)[0])+1
        i_confidence = float(np.max(self.model_I.predict_proba(X)[0]))

        # Étape 4 : Confiance globale = moyenne des deux
        confidence = round((p_confidence + i_confidence) / 2, 2)

        # Étape 5 : Déterminer la source
        source = "ml" if confidence >= ML_CONFIDENCE_THRESHOLD else "ml_low_confidence"

        logger.debug(
            f"Prédiction ML : P={p} (conf={p_confidence:.2f}), "
            f"I={i} (conf={i_confidence:.2f}), "
            f"global={confidence:.2f}, source={source}"
        )

        return MLPrediction(
            probability=p,
            impact=i,
            confidence=confidence,
            source=source,
        )

    # ============================================================
    # SAUVEGARDE / CHARGEMENT
    # ============================================================

    def save(self, path: str = MODEL_PATH):
        """Sauvegarde le modèle sur disque (fichier .pkl)."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump(
            {
                "vectorizer": self.vectorizer,
                "model_P": self.model_P,
                "model_I": self.model_I,
            },
            path,
        )
        logger.info(f"Modèle sauvegardé : {path}")

    def load(self, path: str = MODEL_PATH) -> bool:
        """Charge un modèle depuis le disque."""
        if not os.path.exists(path):
            logger.warning(f"Aucun modèle trouvé à : {path}")
            return False

        data = joblib.load(path)
        self.vectorizer = data["vectorizer"]
        self.model_P = data["model_P"]
        self.model_I = data["model_I"]
        self.is_trained = True
        logger.info(f"Modèle chargé depuis : {path}")
        return True