"""
Entraînement — GaussianNB, KNN et Decision Tree + SentenceTransformers (5 CLASSES)

Métriques : Accuracy, Precision, Recall, F1-Score par classe.

Usage :
    python -m app.ai_workflows.risk_analysis.ml.train --model gnb
    python -m app.ai_workflows.risk_analysis.ml.train --model knn
    python -m app.ai_workflows.risk_analysis.ml.train --model dt
    python -m app.ai_workflows.risk_analysis.ml.train --model all
"""

import logging
import os
import sys
import re

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier

from .nb_embed import (
    GaussianNBEmbedModel, MODEL_PATH_GNB,
    KNNEmbedModel, MODEL_PATH_KNN,
    DecisionTreeEmbedModel, MODEL_PATH_DT,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DATASET_PATH = "data/risk_dataset.xlsx"
FEEDBACK_PATH = "data/risk_feedback.xlsx"

COLUMN_ALIASES = {
    "user_story":          ["user story", "user_story", "us", "story", "histoire utilisateur"],
    "acceptance_criteria": ["acceptance criteria", "acceptance_criteria", "ac",
                            "critères d'acceptation", "criteres acceptation",
                            "criteres_acceptation", "critères_acceptation"],
    "probability":         ["probability", "probabilité", "probabilite", "prob", "p"],
    "impact":              ["impact", "i"],
}


def _clean(text) -> str:
    if not isinstance(text, str):
        text = str(text) if pd.notna(text) else ""
    text = re.sub(r'\s*\[\d+-\d+-\d+\]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for col in df.columns:
            if col.strip().lower() in aliases and canonical not in df.columns:
                rename[col] = canonical
                break
    if rename:
        logger.info(f"Colonnes renommées : {rename}")
        df = df.rename(columns=rename)
    return df


def load_data() -> pd.DataFrame:
    if not os.path.exists(DATASET_PATH):
        logger.error(f"Dataset introuvable : {DATASET_PATH}")
        sys.exit(1)

    df = pd.read_excel(DATASET_PATH)
    df = _normalize_columns(df)
    logger.info(f"Dataset : {len(df)} exemples | colonnes : {list(df.columns)}")

    if os.path.exists(FEEDBACK_PATH):
        fb = pd.read_excel(FEEDBACK_PATH)
        fb = _normalize_columns(fb)
        if "corrected_probability" in fb.columns:
            fb = fb.rename(columns={"corrected_probability": "probability", "corrected_impact": "impact"})
        df = pd.concat([df, fb], ignore_index=True)
        logger.info(f"Feedback ajouté : total {len(df)} exemples")

    return df


def evaluate(y_true: list, y_pred: list, label: str):
    acc = accuracy_score(y_true, y_pred)
    macro_f1 = f1_score(y_true, y_pred, average="macro", zero_division=0)

    logger.info(f"\n{'='*55}")
    logger.info(f"ÉVALUATION — {label}")
    logger.info(f"{'='*55}")
    logger.info(f"Accuracy : {acc:.4f} ({acc:.1%})")
    logger.info(f"Macro F1  : {macro_f1:.4f}")
    logger.info("")
    logger.info(f"{'Classe':>7}  {'Precision':>10}  {'Recall':>8}  {'F1-Score':>10}  {'Support':>8}")
    logger.info(f"{'-------':>7}  {'----------':>10}  {'--------':>8}  {'----------':>10}  {'-------':>8}")

    report = classification_report(
        y_true, y_pred,
        labels=sorted(set(y_true)),
        output_dict=True,
        zero_division=0,
    )
    for c in sorted(set(y_true)):
        r = report[str(c)]
        logger.info(f"{c:>7}  {r['precision']:>10.4f}  {r['recall']:>8.4f}  {r['f1-score']:>10.4f}  {int(r['support']):>8d}")


# ── GaussianNB ──────────────────────────────────────────────────────────────────

def _best_gnb(X_train, y_train, label: str) -> GaussianNB:
    param_grid = {"var_smoothing": np.logspace(-9, -1, 20)}
    grid = GridSearchCV(
        GaussianNB(), param_grid=param_grid,
        cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=42),
        scoring="accuracy", n_jobs=-1,
    )
    grid.fit(X_train, y_train)
    logger.info(f"  {label} → var_smoothing={grid.best_params_['var_smoothing']:.2e} | CV={grid.best_score_:.3f}")
    return grid.best_estimator_


def main_gnb():
    logger.info("=" * 55)
    logger.info("ENTRAÎNEMENT — GaussianNB + SentenceTransformers (5 CLASSES)")
    logger.info("=" * 55)

    df = load_data()
    df["user_story"] = df["user_story"].apply(_clean)
    df["acceptance_criteria"] = df["acceptance_criteria"].apply(_clean)
    df["text"] = df["user_story"] + " " + df["acceptance_criteria"].fillna("")

    texts = df["text"].tolist()
    y_P = df["probability"].astype(int).tolist()
    y_I = df["impact"].astype(int).tolist()

    X_train_txt, X_test_txt, y_train_P, y_test_P, y_train_I, y_test_I = train_test_split(
        texts, y_P, y_I, test_size=0.2, random_state=42, stratify=y_P,
    )
    logger.info(f"Train : {len(X_train_txt)} | Test : {len(X_test_txt)}")

    gnb_model = GaussianNBEmbedModel()
    logger.info("Encodage...")
    X_train = gnb_model.encode(X_train_txt)
    X_test = gnb_model.encode(X_test_txt)
    logger.info(f"Dimensions : {X_train.shape[1]}")

    logger.info("GridSearch P...")
    gnb_model.model_P = _best_gnb(X_train, y_train_P, "P")
    logger.info("GridSearch I...")
    gnb_model.model_I = _best_gnb(X_train, y_train_I, "I")
    gnb_model.is_trained = True

    evaluate(y_test_P, gnb_model.model_P.predict(X_test).tolist(), "GaussianNB — P (Probabilité)")
    evaluate(y_test_I, gnb_model.model_I.predict(X_test).tolist(), "GaussianNB — I (Impact)")

    gnb_model.save(MODEL_PATH_GNB)
    logger.info(f"\nModèle sauvegardé : {MODEL_PATH_GNB}")


# ── KNN ────────────────────────────────────────────────────────────────────────

def _best_knn(X_train, y_train, label: str) -> KNeighborsClassifier:
    param_grid = {
        "n_neighbors": [7, 9, 11, 15, 21, 31, 41],
        "weights": ["uniform", "distance"],
    }
    grid = GridSearchCV(
        KNeighborsClassifier(metric="cosine", algorithm="brute"),
        param_grid=param_grid,
        cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=42),
        scoring="f1_macro", n_jobs=-1,
    )
    grid.fit(X_train, y_train)
    logger.info(f"  {label} → k={grid.best_params_['n_neighbors']}, "
                f"weights={grid.best_params_['weights']} | CV={grid.best_score_:.3f}")
    return grid.best_estimator_


def main_knn():
    logger.info("=" * 55)
    logger.info("ENTRAÎNEMENT — KNN + SentenceTransformers (5 CLASSES)")
    logger.info("=" * 55)

    df = load_data()
    df["user_story"] = df["user_story"].apply(_clean)
    df["acceptance_criteria"] = df["acceptance_criteria"].apply(_clean)
    df["text"] = df["user_story"] + " " + df["acceptance_criteria"].fillna("")

    texts = df["text"].tolist()
    y_P = df["probability"].astype(int).tolist()
    y_I = df["impact"].astype(int).tolist()

    X_train_txt, X_test_txt, y_train_P, y_test_P, y_train_I, y_test_I = train_test_split(
        texts, y_P, y_I, test_size=0.2, random_state=42, stratify=y_P,
    )
    logger.info(f"Train : {len(X_train_txt)} | Test : {len(X_test_txt)}")

    knn_model = KNNEmbedModel()
    logger.info("Encodage...")
    X_train = knn_model.encode(X_train_txt)
    X_test = knn_model.encode(X_test_txt)
    logger.info(f"Dimensions : {X_train.shape[1]}")

    logger.info("GridSearch P...")
    knn_model.model_P = _best_knn(X_train, y_train_P, "P")
    logger.info("GridSearch I...")
    knn_model.model_I = _best_knn(X_train, y_train_I, "I")
    knn_model.is_trained = True

    evaluate(y_test_P, knn_model.model_P.predict(X_test).tolist(), "KNN — P (Probabilité)")
    evaluate(y_test_I, knn_model.model_I.predict(X_test).tolist(), "KNN — I (Impact)")

    knn_model.save(MODEL_PATH_KNN)
    logger.info(f"\nModèle sauvegardé : {MODEL_PATH_KNN}")


# ── Decision Tree ───────────────────────────────────────────────────────────────

def _best_dt(X_train, y_train, label: str) -> DecisionTreeClassifier:
    param_grid = {
        "criterion":          ["gini", "entropy"],
        "max_depth":          [5, 10, 15, 20, None],
        "min_samples_split":  [2, 5, 10],
        "min_samples_leaf":   [1, 2, 4],
        "max_features":       ["sqrt", "log2", None],
        "class_weight":       [None, "balanced"],
    }
    grid = GridSearchCV(
        DecisionTreeClassifier(random_state=42),
        param_grid=param_grid,
        cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=42),
        scoring="accuracy", n_jobs=-1,
    )
    grid.fit(X_train, y_train)
    p = grid.best_params_
    logger.info(
        f"  {label} → criterion={p['criterion']}, max_depth={p['max_depth']}, "
        f"min_samples_split={p['min_samples_split']}, min_samples_leaf={p['min_samples_leaf']}, "
        f"max_features={p['max_features']}, class_weight={p['class_weight']} "
        f"| CV={grid.best_score_:.3f}"
    )
    return grid.best_estimator_


def main_dt():
    logger.info("=" * 55)
    logger.info("ENTRAÎNEMENT — Decision Tree + SentenceTransformers (5 CLASSES)")
    logger.info("=" * 55)

    df = load_data()
    df["user_story"] = df["user_story"].apply(_clean)
    df["acceptance_criteria"] = df["acceptance_criteria"].apply(_clean)
    df["text"] = df["user_story"] + " " + df["acceptance_criteria"].fillna("")

    texts = df["text"].tolist()
    y_P = df["probability"].astype(int).tolist()
    y_I = df["impact"].astype(int).tolist()

    X_train_txt, X_test_txt, y_train_P, y_test_P, y_train_I, y_test_I = train_test_split(
        texts, y_P, y_I, test_size=0.2, random_state=42, stratify=y_P,
    )
    logger.info(f"Train : {len(X_train_txt)} | Test : {len(X_test_txt)}")

    dt_model = DecisionTreeEmbedModel()
    logger.info("Encodage...")
    X_train = dt_model.encode(X_train_txt)
    X_test = dt_model.encode(X_test_txt)
    logger.info(f"Dimensions : {X_train.shape[1]}")

    logger.info("GridSearch P...")
    dt_model.model_P = _best_dt(X_train, y_train_P, "P")
    logger.info("GridSearch I...")
    dt_model.model_I = _best_dt(X_train, y_train_I, "I")
    dt_model.is_trained = True

    evaluate(y_test_P, dt_model.model_P.predict(X_test).tolist(), "Decision Tree — P (Probabilité)")
    evaluate(y_test_I, dt_model.model_I.predict(X_test).tolist(), "Decision Tree — I (Impact)")

    dt_model.save(MODEL_PATH_DT)
    logger.info(f"\nModèle sauvegardé : {MODEL_PATH_DT}")


# ── Main ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Entraînement Risk Analysis ML")
    parser.add_argument("--model", choices=["gnb", "knn", "dt", "all"], default="knn")
    args = parser.parse_args()

    if args.model == "gnb":
        main_gnb()
    elif args.model == "knn":
        main_knn()
    elif args.model == "dt":
        main_dt()
    else:
        main_gnb()
        logger.info("\n" + "=" * 55)
        main_knn()
        logger.info("\n" + "=" * 55)
        main_dt()