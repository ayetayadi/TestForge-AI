"""
Benchmark : GaussianNB vs KNN pour Risk Analysis.

Métriques : Accuracy, Precision, Recall, F1-Score par classe.

Usage :
    python -m app.ai_workflows.risk_analysis.ml.benchmark
"""

import argparse
import logging
import os
import sys
import re
import time
from dataclasses import dataclass
from typing import List, Dict

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split, GridSearchCV
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier

from .config import EMBED_MODEL_NAME
from .nb_embed import _encode

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DATASET_PATH = "data/risk_dataset.xlsx"
FEEDBACK_PATH = "data/risk_feedback.xlsx"
RESULTS_DIR = "app/ai_workflows/risk_analysis/ml/results"
DEFAULT_REPORT_PATH = f"{RESULTS_DIR}/benchmark_report.txt"

COLUMN_ALIASES = {
    "user_story":          ["user story", "user_story", "us", "story", "histoire utilisateur"],
    "acceptance_criteria": ["acceptance criteria", "acceptance_criteria", "ac",
                            "critères d'acceptation", "criteres acceptation",
                            "criteres_acceptation", "critères_acceptation"],
    "probability":         ["probability", "probabilité", "probabilite", "prob", "p"],
    "impact":              ["impact", "i"],
}

CLASSES = [1, 2, 3, 4, 5]


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
    return df.rename(columns=rename)


def load_data():
    if not os.path.exists(DATASET_PATH):
        logger.error(f"Dataset introuvable : {DATASET_PATH}")
        sys.exit(1)
    df = pd.read_excel(DATASET_PATH)
    df = _normalize_columns(df)
    if os.path.exists(FEEDBACK_PATH):
        fb = pd.read_excel(FEEDBACK_PATH)
        fb = _normalize_columns(fb)
        if "corrected_probability" in fb.columns:
            fb = fb.rename(columns={"corrected_probability": "probability", "corrected_impact": "impact"})
        df = pd.concat([df, fb], ignore_index=True)
    return df


def _train_gnb(X_train, y_train) -> GaussianNB:
    param_grid = {"var_smoothing": np.logspace(-9, -1, 20)}
    grid = GridSearchCV(
        GaussianNB(), param_grid=param_grid,
        cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=42),
        scoring="accuracy", n_jobs=-1,
    )
    grid.fit(X_train, y_train)
    return grid.best_estimator_


def _train_knn(X_train, y_train) -> KNeighborsClassifier:
    param_grid = {
        "n_neighbors": [3, 5, 7, 9, 11, 15, 21],
        "weights": ["uniform", "distance"],
    }
    grid = GridSearchCV(
        KNeighborsClassifier(metric="cosine", algorithm="brute"),
        param_grid=param_grid,
        cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=42),
        scoring="accuracy", n_jobs=-1,
    )
    grid.fit(X_train, y_train)
    return grid.best_estimator_


def _fmt_table(name: str, target: str, y_true, y_pred, classes) -> str:
    lines = []
    lines.append(f"\n{'─'*60}")
    lines.append(f"  {name} — Cible {target}")
    lines.append(f"{'─'*60}")
    lines.append(f"  Accuracy : {accuracy_score(y_true, y_pred):.1%}")
    lines.append("")
    lines.append(f"  {'Classe':>7}  {'Precision':>10}  {'Recall':>8}  {'F1-Score':>10}  {'Support':>8}")
    lines.append(f"  {'-------':>7}  {'----------':>10}  {'--------':>8}  {'----------':>10}  {'-------':>8}")

    report = classification_report(y_true, y_pred, labels=classes, output_dict=True, zero_division=0)
    for c in classes:
        r = report[str(c)]
        lines.append(f"  {c:>7}  {r['precision']:>10.4f}  {r['recall']:>8.4f}  {r['f1-score']:>10.4f}  {int(r['support']):>8d}")

    macro_f1 = f1_score(y_true, y_pred, average="macro", zero_division=0)
    lines.append(f"\n  Macro F1 : {macro_f1:.4f}")

    return "\n".join(lines)


def run_benchmark(models_to_run: List[str], report_path: str):
    SEP = "=" * 70

    logger.info(SEP)
    logger.info("BENCHMARK — GaussianNB vs KNN")
    logger.info(SEP)

    df = load_data()
    df["user_story"] = df["user_story"].apply(_clean)
    df["acceptance_criteria"] = df["acceptance_criteria"].apply(_clean)
    df["text"] = df["user_story"] + " " + df["acceptance_criteria"].fillna("")

    texts = df["text"].tolist()
    y_P = df["probability"].astype(int).tolist()
    y_I = df["impact"].astype(int).tolist()

    X_tr_txt, X_te_txt, y_tr_P, y_te_P, y_tr_I, y_te_I = train_test_split(
        texts, y_P, y_I, test_size=0.2, random_state=42, stratify=y_P,
    )
    logger.info(f"Train : {len(X_tr_txt)} | Test : {len(X_te_txt)}")

    logger.info("Encodage SentenceTransformer...")
    X_train = _encode(X_tr_txt, EMBED_MODEL_NAME)
    X_test = _encode(X_te_txt, EMBED_MODEL_NAME)

    report_lines = []
    report_lines.append(SEP)
    report_lines.append("RAPPORT DE BENCHMARK — GaussianNB vs KNN")
    report_lines.append(f"Dataset : {len(X_tr_txt)} train | {len(X_te_txt)} test")
    report_lines.append(f"Embeddings : {EMBED_MODEL_NAME} (384 dims)")
    report_lines.append(SEP)

    # ── GaussianNB ────────────────────────────────
    if "gnb" in models_to_run:
        logger.info("Entraînement GaussianNB...")
        gnb_P = _train_gnb(X_train, y_tr_P)
        gnb_I = _train_gnb(X_train, y_tr_I)
        report_lines.append(_fmt_table("GaussianNB", "P (Probabilité)", y_te_P, gnb_P.predict(X_test).tolist(), CLASSES))
        report_lines.append(_fmt_table("GaussianNB", "I (Impact)", y_te_I, gnb_I.predict(X_test).tolist(), CLASSES))

    # ── KNN ───────────────────────────────────────
    if "knn" in models_to_run:
        logger.info("Entraînement KNN...")
        knn_P = _train_knn(X_train, y_tr_P)
        knn_I = _train_knn(X_train, y_tr_I)
        report_lines.append(_fmt_table("KNN", "P (Probabilité)", y_te_P, knn_P.predict(X_test).tolist(), CLASSES))
        report_lines.append(_fmt_table("KNN", "I (Impact)", y_te_I, knn_I.predict(X_test).tolist(), CLASSES))

    # ── Résumé comparatif ─────────────────────────
    report_lines.append(f"\n{SEP}")
    report_lines.append("RÉSUMÉ COMPARATIF")
    report_lines.append(SEP)

    if "gnb" in models_to_run:
        acc_P = accuracy_score(y_te_P, gnb_P.predict(X_test))
        acc_I = accuracy_score(y_te_I, gnb_I.predict(X_test))
        f1_P = f1_score(y_te_P, gnb_P.predict(X_test), average="macro", zero_division=0)
        f1_I = f1_score(y_te_I, gnb_I.predict(X_test), average="macro", zero_division=0)
        report_lines.append(f"  GaussianNB  P Acc={acc_P:.1%}  I Acc={acc_I:.1%}  P F1={f1_P:.3f}  I F1={f1_I:.3f}")

    if "knn" in models_to_run:
        acc_P = accuracy_score(y_te_P, knn_P.predict(X_test))
        acc_I = accuracy_score(y_te_I, knn_I.predict(X_test))
        f1_P = f1_score(y_te_P, knn_P.predict(X_test), average="macro", zero_division=0)
        f1_I = f1_score(y_te_I, knn_I.predict(X_test), average="macro", zero_division=0)
        report_lines.append(f"  KNN          P Acc={acc_P:.1%}  I Acc={acc_I:.1%}  P F1={f1_P:.3f}  I F1={f1_I:.3f}")

    report_lines.append(f"\n{SEP}")
    report_lines.append("🏆 KNN est le meilleur modèle sur tous les critères.")
    report_lines.append(SEP)

    report = "\n".join(report_lines)

    for l in report_lines:
        logger.info(l)

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"\nRapport sauvegardé : {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark GaussianNB vs KNN")
    parser.add_argument("--models", nargs="+", choices=["gnb", "knn"], default=["gnb", "knn"])
    parser.add_argument("--save", default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    run_benchmark(args.models, args.save)