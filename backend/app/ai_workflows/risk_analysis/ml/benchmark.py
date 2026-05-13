"""
benchmark.py — Évalue le modèle ML sur le même dataset.

Usage :
    python -m app.ai_workflows.risk_analysis.benchmark

Ce script :
    1. Charge le modèle entraîné
    2. Charge le dataset depuis le même fichier Excel
    3. Utilise le même split (20% test)
    4. Calcule toutes les métriques
    5. Affiche un rapport détaillé
    6. Dit si le modèle est prêt pour la production
"""

import logging
import os
import sys

import pandas as pd
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    confusion_matrix,
    mean_absolute_error,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

MODEL_PATH = "models/risk_ml_model.pkl"
DATASET_PATH = "data/risk_dataset.xlsx"

PRODUCTION_THRESHOLDS = {
    "accuracy_P": 0.75,
    "accuracy_I": 0.75,
    "mae_P": 0.5,
    "mae_I": 0.5,
    "priority_accuracy": 0.85,
    "critical_recall": 0.80,
}


def load_model():
    """Charge le modèle entraîné."""
    if not os.path.exists(MODEL_PATH):
        logger.error(f"❌ Modèle introuvable : {MODEL_PATH}")
        logger.info("   Lancez d'abord train.py")
        sys.exit(1)

    data = joblib.load(MODEL_PATH)
    logger.info(f"✅ Modèle chargé (entraîné le {data.get('trained_at', 'inconnue')})")
    return data["vectorizer"], data["model_P"], data["model_I"]


def load_and_split_data():
    """Charge le dataset depuis Excel et fait le même split 80/20."""
    if not os.path.exists(DATASET_PATH):
        logger.error(f"❌ Dataset introuvable : {DATASET_PATH}")
        logger.info("   Créez un fichier Excel avec les colonnes :")
        logger.info("   user_story, acceptance_criteria, probability, impact")
        sys.exit(1)

    df = pd.read_excel(DATASET_PATH)
    df["text"] = df["user_story"] + " " + df["acceptance_criteria"].fillna("")

    # Même split que train.py (random_state=42)
    _, X_test_text, _, y_test_P, _, y_test_I = train_test_split(
        df["text"].tolist(),
        df["probability"].astype(int).tolist(),
        df["impact"].astype(int).tolist(),
        test_size=0.2,
        random_state=42,
    )

    logger.info(f"✅ Dataset chargé : {len(df)} exemples → Test : {len(X_test_text)}")
    return X_test_text, y_test_P, y_test_I


def classify_priority(score: int) -> str:
    """Classe le score en priorité."""
    if score >= 20:
        return "critical"
    if score >= 12:
        return "high"
    if score >= 6:
        return "medium"
    return "low"


def compute_all_metrics(y_true_P, y_true_I, y_pred_P, y_pred_I):
    """Calcule toutes les métriques d'évaluation."""
    y_true_P = np.array(y_true_P, dtype=int)
    y_true_I = np.array(y_true_I, dtype=int)
    y_pred_P = np.array(y_pred_P, dtype=int)
    y_pred_I = np.array(y_pred_I, dtype=int)

    acc_P = accuracy_score(y_true_P, y_pred_P)
    acc_I = accuracy_score(y_true_I, y_pred_I)
    mae_P = mean_absolute_error(y_true_P, y_pred_P)
    mae_I = mean_absolute_error(y_true_I, y_pred_I)

    precision_P, recall_P, f1_P, _ = precision_recall_fscore_support(
        y_true_P, y_pred_P, average="weighted", zero_division=0
    )
    precision_I, recall_I, f1_I, _ = precision_recall_fscore_support(
        y_true_I, y_pred_I, average="weighted", zero_division=0
    )

    cm_P = confusion_matrix(y_true_P, y_pred_P, labels=[1, 2, 3, 4, 5])
    cm_I = confusion_matrix(y_true_I, y_pred_I, labels=[1, 2, 3, 4, 5])

    true_scores = y_true_P * y_true_I
    pred_scores = y_pred_P * y_pred_I
    true_priorities = [classify_priority(s) for s in true_scores]
    pred_priorities = [classify_priority(s) for s in pred_scores]
    priority_acc = accuracy_score(true_priorities, pred_priorities)

    true_critical = [1 if p == "critical" else 0 for p in true_priorities]
    pred_critical = [1 if p == "critical" else 0 for p in pred_priorities]
    _, critical_recall, _, _ = precision_recall_fscore_support(
        true_critical, pred_critical, average="binary", zero_division=0
    )

    extreme_errors_P = sum(abs(y_true_P - y_pred_P) >= 2)
    extreme_errors_I = sum(abs(y_true_I - y_pred_I) >= 2)

    return {
        "accuracy_P": round(acc_P, 3),
        "accuracy_I": round(acc_I, 3),
        "mae_P": round(mae_P, 3),
        "mae_I": round(mae_I, 3),
        "f1_P": round(f1_P, 3),
        "f1_I": round(f1_I, 3),
        "priority_accuracy": round(priority_acc, 3),
        "critical_recall": round(critical_recall, 3),
        "extreme_errors_P": extreme_errors_P,
        "extreme_errors_I": extreme_errors_I,
        "cm_P": cm_P,
        "cm_I": cm_I,
    }


def print_confusion_matrix(cm, title: str):
    """Affiche une matrice de confusion lisible."""
    print(f"\n📊 Matrice de confusion — {title}")
    print("           Prédit")
    print("           1    2    3    4    5")
    for i, label in enumerate([1, 2, 3, 4, 5]):
        row = "  ".join(f"{cm[i][j]:3d}" for j in range(5))
        print(f"Vrai {label}  [{row}]")


def print_report(metrics: dict):
    """Affiche le rapport complet."""
    print("\n" + "=" * 60)
    print("📊 RAPPORT DE BENCHMARK — RISK-BASED TESTING ML")
    print("=" * 60)

    print("\n─── MÉTRIQUES PRINCIPALES ───")
    print(f"Accuracy P           : {metrics['accuracy_P']:.1%}")
    print(f"Accuracy I           : {metrics['accuracy_I']:.1%}")
    print(f"MAE P                : {metrics['mae_P']:.2f} niveaux")
    print(f"MAE I                : {metrics['mae_I']:.2f} niveaux")
    print(f"F1-Score P           : {metrics['f1_P']:.1%}")
    print(f"F1-Score I           : {metrics['f1_I']:.1%}")

    print("\n─── MÉTRIQUES MÉTIER ───")
    print(f"Priority Accuracy    : {metrics['priority_accuracy']:.1%}")
    print(f"Critical Recall      : {metrics['critical_recall']:.1%}")

    print("\n─── ERREURS GRAVES (>1 niveau d'écart) ───")
    print(f"Erreurs P            : {metrics['extreme_errors_P']}")
    print(f"Erreurs I            : {metrics['extreme_errors_I']}")

    print_confusion_matrix(metrics["cm_P"], "Probabilité (P)")
    print_confusion_matrix(metrics["cm_I"], "Impact (I)")

    print("\n" + "=" * 60)
    print("🏆 VERDICT PRODUCTION")
    print("=" * 60)

    checks = {
        "Accuracy P ≥ 75%": metrics["accuracy_P"] >= PRODUCTION_THRESHOLDS["accuracy_P"],
        "Accuracy I ≥ 75%": metrics["accuracy_I"] >= PRODUCTION_THRESHOLDS["accuracy_I"],
        "MAE P < 0.5": metrics["mae_P"] < PRODUCTION_THRESHOLDS["mae_P"],
        "MAE I < 0.5": metrics["mae_I"] < PRODUCTION_THRESHOLDS["mae_I"],
        "Priority Acc ≥ 85%": metrics["priority_accuracy"] >= PRODUCTION_THRESHOLDS["priority_accuracy"],
        "Critical Recall ≥ 80%": metrics["critical_recall"] >= PRODUCTION_THRESHOLDS["critical_recall"],
        "Pas d'erreurs extrêmes P": metrics["extreme_errors_P"] == 0,
        "Pas d'erreurs extrêmes I": metrics["extreme_errors_I"] == 0,
    }

    all_pass = True
    for check, passed in checks.items():
        symbol = "✅" if passed else "❌"
        print(f"{symbol} {check}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("✅ MODÈLE PRÊT POUR LA PRODUCTION !")
    else:
        print("⚠️ MODÈLE PAS ENCORE PRÊT. Améliorez le dataset ou les paramètres.")
        print("   Les ❌ indiquent les points à améliorer.")

def main():
    """Fonction principale du benchmark."""
    vectorizer, model_P, model_I = load_model()
    X_test_text, y_test_P, y_test_I = load_and_split_data()
    X_test = vectorizer.transform(X_test_text)

    y_pred_P_raw = model_P.predict(X_test)
    y_pred_I_raw = model_I.predict(X_test)
    
    # +1 et conversion en listes d'entiers
    y_pred_P = [int(y) + 1 for y in y_pred_P_raw]
    y_pred_I = [int(y) + 1 for y in y_pred_I_raw]

    metrics = compute_all_metrics(y_test_P, y_test_I, y_pred_P, y_pred_I)
    print_report(metrics)
    
  
if __name__ == "__main__":
    main()