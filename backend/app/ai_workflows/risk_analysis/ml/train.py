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
import re
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


def clean_text(text: str) -> str:
    """
    Nettoie le texte :
    - Supprime les annotations [X-Y-Z] ou [X-Y] en fin de phrase
    - Supprime les numéros isolés
    """
    # Supprimer [4-1-7], [1-5-12], [5-2], etc.
    text = re.sub(r'\s*\[\d+-\d+-\d+\]', '', text)
    text = re.sub(r'\s*\[\d+-\d+\]', '', text)
    
    # Supprimer les espaces multiples
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

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
    # Nettoyer d'abord
    df["user_story"] = df["user_story"].apply(clean_text)
    df["acceptance_criteria"] = df["acceptance_criteria"].apply(clean_text)
    
    # Puis concaténer
    df["text"] = df["user_story"] + " " + df["acceptance_criteria"].fillna("")
    y_P = df["probability"].astype(int)
    
    # Fusionner I en 3 classes : 1,2→1  3→2  4,5→3
    y_I_raw = df["impact"].astype(int)
    y_I = y_I_raw.map({1:1, 2:1, 3:2, 4:3, 5:3})
    
    return df["text"].tolist(), y_P.tolist(), y_I.tolist()

def check_consistency(df: pd.DataFrame):
    """Vérifie la cohérence des annotations."""
    logger.info("\n📊 VÉRIFICATION DE COHÉRENCE")
    
    # Distribution
    logger.info("\nDistribution P :")
    for val in sorted(df["probability"].unique()):
        count = (df["probability"] == val).sum()
        logger.info(f"  P={val} : {count} ({count/len(df)*100:.0f}%)")
    
    logger.info("\nDistribution I :")
    for val in sorted(df["impact"].unique()):
        count = (df["impact"] == val).sum()
        logger.info(f"  I={val} : {count} ({count/len(df)*100:.0f}%)")
    
    # Score = P × I
    df["score"] = df["probability"] * df["impact"]
    logger.info("\nDistribution Score :")
    logger.info(f"  Min : {df['score'].min()}")
    logger.info(f"  Max : {df['score'].max()}")
    logger.info(f"  Moyenne : {df['score'].mean():.1f}")
    
    # Vérifier que P=1 est bien pour des US simples
    low_p = df[df["probability"] == 1]["user_story"].head(3).tolist()
    logger.info("\nExemples P=1 (faible risque) :")
    for us in low_p:
        logger.info(f"  - {us[:100]}...")
    
    high_p = df[df["probability"] == 5]["user_story"].head(3).tolist()
    logger.info("\nExemples P=5 (haut risque) :")
    for us in high_p:
        logger.info(f"  - {us[:100]}...")

def train_model(X_train, y_train_P, y_train_I):
    """
    Entraîne deux modèles XGBoost : un pour P (5 classes), un pour I (3 classes).
    """
    logger.info("Entraînement du modèle...")

    # LabelEncoder pour P : 5 classes [1,2,3,4,5] → [0,1,2,3,4]
    le_P = LabelEncoder()
    le_P.fit([1, 2, 3, 4, 5])
    y_train_P_enc = le_P.transform(y_train_P)

    # LabelEncoder pour I : 3 classes [1,2,3] → [0,1,2]
    le_I = LabelEncoder()
    le_I.fit([1, 2, 3])
    y_train_I_enc = le_I.transform(y_train_I)

    # Poids de classe pour I
    from sklearn.utils.class_weight import compute_class_weight
    import numpy as np
    classes_i = np.unique(y_train_I_enc)
    weights_i = compute_class_weight('balanced', classes=classes_i, y=y_train_I_enc)
    sample_weights_i = weights_i[y_train_I_enc]

    # Modèle P (5 classes)
    model_P = XGBClassifier(
        n_estimators=150, max_depth=3, learning_rate=0.08,
        random_state=42, subsample=0.8, colsample_bytree=0.8,
        objective="multi:softprob", verbosity=0
    )
    model_P.fit(X_train, y_train_P_enc)

    # Modèle I (3 classes)
    model_I = XGBClassifier(
        n_estimators=150, max_depth=3, learning_rate=0.08,
        random_state=42, subsample=0.8, colsample_bytree=0.8,
        objective="multi:softprob", verbosity=0
    )
    model_I.fit(X_train, y_train_I_enc, sample_weight=sample_weights_i)

    model_P.label_encoder_ = le_P
    model_I.label_encoder_ = le_I
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

def auto_correct_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Corrige automatiquement les labels incohérents basés sur des mots-clés.
    """
    corrections = 0
    
    # Mots qui indiquent FORCÉMENT un risque élevé
    high_risk_p = [
        'payment', 'pay', 'transaction', 'checkout', 'billing', 'wire transfer',
        '2fa', 'mfa', 'multi-factor', 'encrypt', 'fraud', 'oauth', 'otp',
        'concurrency', 'race condition', 'deadlock', 'rollback',
        'personal data', 'sensitive', 'api key', 'audit log'
    ]
    
    # Mots qui indiquent FORCÉMENT un impact élevé
    high_impact = [
        'payment', 'pay', 'transaction', 'billing', 'wire transfer',
        'fraud', 'regulatory', 'compliance', 'legal', 'audit',
        'personal data', 'gdpr', 'pii', 'sensitive', 'financial'
    ]
    
    # Mots qui indiquent FORCÉMENT un risque faible
    low_risk = [
        'color', 'colour', 'font', 'tooltip', 'label', 'wording', 'typo',
        'icon', 'cosmetic', 'spelling', 'grammar', 'bookmark',
        'sort', 'faq', 'help page', 'documentation'
    ]
    
    for idx, row in df.iterrows():
        text = (str(row['user_story']) + ' ' + str(row['acceptance_criteria'])).lower()
        p, i = row['probability'], row['impact']
        
        # P trop bas pour du paiement/sécurité (et pas cosmétique)
        if any(w in text for w in high_risk_p) and p <= 2 and not any(w in text for w in low_risk):
            df.at[idx, 'probability'] = 4
            corrections += 1
        
        # I trop bas pour du paiement/sécurité
        if any(w in text for w in high_impact) and i <= 2 and not any(w in text for w in low_risk):
            df.at[idx, 'impact'] = 4
            corrections += 1
        
        # P trop haut pour du cosmétique (et pas de paiement)
        if any(w in text for w in low_risk) and p >= 4 and not any(w in text for w in high_risk_p):
            df.at[idx, 'probability'] = 2
            corrections += 1
    
    logger.info(f"🔧 {corrections} labels corrigés automatiquement")
    return df

def main():
    """Fonction principale du script d'entraînement."""
    logger.info("=" * 60)
    logger.info("ENTRAÎNEMENT DU MODÈLE RISK-BASED TESTING")
    logger.info("=" * 60)

    # 1. Charger les données
    df = load_data(DATASET_PATH, FEEDBACK_PATH)  
    check_consistency(df)
    # df = auto_correct_labels(df)
    texts, labels_P, labels_I = prepare_data(df)

    # 2. Diviser en train/test (80/20)
    X_train_text, X_test_text, y_train_P, y_test_P, y_train_I, y_test_I = train_test_split(
        texts, labels_P, labels_I, test_size=0.2, random_state=42
    )
    logger.info(f"Train : {len(X_train_text)}, Test : {len(X_test_text)}")

    # 3. Vectoriser le texte avec TF-IDF
    vectorizer = TfidfVectorizer(
        max_features=TFIDF_MAX_FEATURES,
        stop_words='english',      
        ngram_range=(1, 3),        
        min_df=2,                  
        max_df=0.95,
        sublinear_tf=True                
    )
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
    
        # ACCEPTER si MAE < 0.6 (bonne qualité) même si accuracy légèrement inférieure
        if new_acc < old_acc - 0.05 and metrics["mae_P"] > 0.6:
            logger.warning("⚠️ Le nouveau modèle est MOINS BON. Sauvegarde annulée.")
            sys.exit(1)

    # 7. Sauvegarder
    save_model(vectorizer, model_P, model_I, metrics)
    logger.info("✅ Entraînement terminé avec succès !")


if __name__ == "__main__":
    main()