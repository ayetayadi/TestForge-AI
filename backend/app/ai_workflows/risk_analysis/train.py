"""
train.py — Script d'entraînement du modèle ML pour le Risk-Based Testing.

Usage :
    python -m app.ai_workflows.risk_analysis.train

Ce script :
    1. Charge le dataset annoté (Excel)
    2. Divise en train/test (80/20)
    3. Vectorise le texte avec TF-IDF
    4. Entraîne un XGBoost pour P et un pour I
    5. Évalue sur l'ensemble de test
    6. Sauvegarde le modèle si les performances sont bonnes
"""

import logging
import os
import sys
from datetime import datetime
from sklearn.preprocessing import LabelEncoder
import pandas as pd
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    mean_absolute_error,
)
from xgboost import XGBClassifier

from .config import TFIDF_MAX_FEATURES

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Chemins
DATASET_PATH = "data/risk_dataset.xlsx"
FEEDBACK_PATH = "data/risk_feedback.xlsx"
MODEL_DIR = "models"
MODEL_PATH = os.path.join(MODEL_DIR, "risk_ml_model.pkl")
METRICS_PATH = os.path.join(MODEL_DIR, "metrics.txt")


def load_data(dataset_path: str, feedback_path: str = None) -> pd.DataFrame:
    """
    Charge le dataset initial + les corrections humaines.

    Format Excel attendu :
      user_story | acceptance_criteria | probability | impact
    """
    if not os.path.exists(dataset_path):
        logger.error(f"❌ Dataset introuvable : {dataset_path}")
        logger.info("Créez un fichier Excel avec les colonnes :")
        logger.info("  user_story, acceptance_criteria, probability, impact")
        sys.exit(1)

    df = pd.read_excel(dataset_path)
    logger.info(f"✅ Dataset initial chargé : {len(df)} exemples")

    if feedback_path and os.path.exists(feedback_path):
        feedback_df = pd.read_excel(feedback_path)
        if "corrected_probability" in feedback_df.columns:
            feedback_df = feedback_df.rename(columns={
                "corrected_probability": "probability",
                "corrected_impact": "impact",
            })
        df = pd.concat([df, feedback_df], ignore_index=True)
        logger.info(f"✅ Corrections chargées : {len(feedback_df)} → Total : {len(df)} exemples")

    return df


def prepare_data(df: pd.DataFrame) -> tuple:
    """Combine US + AC en un seul texte et extrait les labels."""
    df["text"] = df["user_story"] + " " + df["acceptance_criteria"].fillna("")
    y_P = df["probability"].astype(int)
    y_I = df["impact"].astype(int)
    return df["text"].tolist(), y_P.tolist(), y_I.tolist()


def train_model(X_train, y_train_P, y_train_I):
    """
    Entraîne deux modèles XGBoost : un pour P, un pour I.
    """
    logger.info("Entraînement du modèle...")

    # LabelEncoder transforme [1,2,3,4,5] → [0,1,2,3,4]
    # On crée un encodeur FIT sur TOUTES les classes possibles (1-5)
    le = LabelEncoder()
    le.fit([1, 2, 3, 4, 5])

    y_train_P_enc = le.transform(y_train_P)
    y_train_I_enc = le.transform(y_train_I)

    # Modèle pour P
    model_P = XGBClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        random_state=42,
    )
    model_P.fit(X_train, y_train_P_enc)

    # Modèle pour I
    model_I = XGBClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        random_state=42,
    )
    model_I.fit(X_train, y_train_I_enc)

    # Sauvegarder l'encodeur avec le modèle
    model_P.label_encoder_ = le
    model_I.label_encoder_ = le

    return model_P, model_I

def evaluate_model(vectorizer, model_P, model_I, X_test, y_test_P, y_test_I) -> dict:
    """Évalue les modèles sur l'ensemble de test."""
    # Prédictions (classes 0-4)
    y_pred_P_enc = model_P.predict(X_test)
    y_pred_I_enc = model_I.predict(X_test)
    
    # Reconvertir 0-4 → 1-5
    y_pred_P = [y + 1 for y in y_pred_P_enc]
    y_pred_I = [y + 1 for y in y_pred_I_enc]

    # Métriques
    acc_P = accuracy_score(y_test_P, y_pred_P)
    acc_I = accuracy_score(y_test_I, y_pred_I)
    mae_P = mean_absolute_error(y_test_P, y_pred_P)
    mae_I = mean_absolute_error(y_test_I, y_pred_I)

    logger.info(f"Accuracy P : {acc_P:.2f}")
    logger.info(f"Accuracy I : {acc_I:.2f}")
    logger.info(f"MAE P      : {mae_P:.2f}")
    logger.info(f"MAE I      : {mae_I:.2f}")

    return {
        "accuracy_P": acc_P,
        "accuracy_I": acc_I,
        "mae_P": mae_P,
        "mae_I": mae_I,
        "n_test": len(y_test_P),
    }

def load_old_metrics() -> dict:
    """Charge les métriques de l'ancien modèle pour comparaison."""
    if os.path.exists(METRICS_PATH):
        with open(METRICS_PATH, "r") as f:
            lines = f.readlines()
            metrics = {}
            for line in lines:
                key, val = line.strip().split("=")
                metrics[key] = float(val)
            return metrics
    return {}


def save_model(vectorizer, model_P, model_I, metrics: dict):
    """Sauvegarde le modèle et ses métriques."""
    os.makedirs(MODEL_DIR, exist_ok=True)

    joblib.dump(
        {
            "vectorizer": vectorizer,
            "model_P": model_P,
            "model_I": model_I,
            "trained_at": datetime.now().isoformat(),
        },
        MODEL_PATH,
    )
    logger.info(f"✅ Modèle sauvegardé : {MODEL_PATH}")

    with open(METRICS_PATH, "w") as f:
        for key, val in metrics.items():
            f.write(f"{key}={val}\n")
    logger.info(f"✅ Métriques sauvegardées : {METRICS_PATH}")


def main():
    """Fonction principale du script d'entraînement."""
    logger.info("=" * 60)
    logger.info("ENTRAÎNEMENT DU MODÈLE RISK-BASED TESTING")
    logger.info("=" * 60)

    # 1. Charger les données
    df = load_data(DATASET_PATH, FEEDBACK_PATH)
    texts, labels_P, labels_I = prepare_data(df)

    # 2. Diviser en train/test (80/20)
    X_train_text, X_test_text, y_train_P, y_test_P, y_train_I, y_test_I = train_test_split(
        texts, labels_P, labels_I, test_size=0.2, random_state=42
    )
    logger.info(f"Train : {len(X_train_text)}, Test : {len(X_test_text)}")

    # 3. Vectoriser le texte avec TF-IDF
    vectorizer = TfidfVectorizer(max_features=TFIDF_MAX_FEATURES)
    X_train = vectorizer.fit_transform(X_train_text)
    X_test = vectorizer.transform(X_test_text)
    logger.info(f"TF-IDF : {len(vectorizer.get_feature_names_out())} features")

    # 4. Entraîner les modèles
    model_P, model_I = train_model(X_train, y_train_P, y_train_I)

    # 5. Évaluer
    metrics = evaluate_model(vectorizer, model_P, model_I, X_test, y_test_P, y_test_I)

    # 6. Comparer avec l'ancien modèle
    old_metrics = load_old_metrics()
    if old_metrics:
        old_acc = (old_metrics.get("accuracy_P", 0) + old_metrics.get("accuracy_I", 0)) / 2
        new_acc = (metrics["accuracy_P"] + metrics["accuracy_I"]) / 2
        logger.info(f"Ancien accuracy moyen : {old_acc:.2f}")
        logger.info(f"Nouvel accuracy moyen : {new_acc:.2f}")

        if new_acc < old_acc:
            logger.warning("⚠️ Le nouveau modèle est MOINS BON. Sauvegarde annulée.")
            logger.warning("   Vérifiez la qualité des nouvelles annotations.")
            sys.exit(1)

    # 7. Sauvegarder
    save_model(vectorizer, model_P, model_I, metrics)
    logger.info("✅ Entraînement terminé avec succès !")


if __name__ == "__main__":
    main()