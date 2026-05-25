"""
Benchmark : GaussianNB vs KNN vs Decision Tree pour Risk Analysis.

Métriques : Accuracy, Precision, Recall, F1-Score par classe.
Courbes   : Performance vs Complexité (train + test) par modèle.

Usage :
    python -m app.ai_workflows.risk_analysis.ml.benchmark
    python -m app.ai_workflows.risk_analysis.ml.benchmark --models gnb knn dt
"""

import argparse
import logging
import os
import sys
import re
import time
from typing import List

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split, GridSearchCV
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier

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
    logger.info(f"    GNB best var_smoothing={grid.best_params_['var_smoothing']:.2e} | CV={grid.best_score_:.3f}")
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
    logger.info(f"    KNN best k={grid.best_params_['n_neighbors']}, weights={grid.best_params_['weights']} | CV={grid.best_score_:.3f}")
    return grid.best_estimator_


def _train_dt(X_train, y_train) -> DecisionTreeClassifier:
    param_grid = {
        "criterion":         ["gini", "entropy"],
        "max_depth":         [5, 10, 15, 20, None],
        "min_samples_split": [2, 5, 10],
        "min_samples_leaf":  [1, 2, 4],
        "max_features":      ["sqrt", "log2", None],
        "class_weight":      [None, "balanced"],
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
        f"    DT best criterion={p['criterion']}, max_depth={p['max_depth']}, "
        f"max_features={p['max_features']}, class_weight={p['class_weight']} | CV={grid.best_score_:.3f}"
    )
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


# ── Courbes performance vs complexité ─────────────────────────────────────────

def _plot_complexity_curves(X_train, X_test, y_train_P, y_test_P, y_train_I, y_test_I):
    """
    Pour chaque modèle : 2 courbes en fonction du paramètre de complexité.
      - Courbe 1 : Performance d'apprentissage  (train,  bleu)  — prédit sur X_train
      - Courbe 2 : Performance de généralisation (test,   rouge) — prédit sur X_test
    Score = moyenne(accuracy_P, accuracy_I).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib non installé — courbes ignorées")
        return

    os.makedirs(RESULTS_DIR, exist_ok=True)

    def _draw(ax, train_scores, test_scores, x_pos, x_labels, xlabel, title):
        ax.plot(x_pos, train_scores, "o-",  color="steelblue", linewidth=2, label="Apprentissage (train)")
        ax.plot(x_pos, test_scores,  "s--", color="tomato",    linewidth=2, label="Généralisation (test)")
        ax.set_xticks(x_pos)
        ax.set_xticklabels(x_labels, fontsize=9)
        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel("Accuracy", fontsize=10)
        ax.set_ylim(0.0, 1.05)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    # ── 1. Decision Tree — complexité = max_depth ──────────────────────────
    logger.info("  Courbe complexité — Decision Tree...")
    depths = [1, 2, 3, 5, 7, 10, 15, 20]
    train_scores, test_scores = [], []

    for d in depths:
        dt = DecisionTreeClassifier(max_depth=d, random_state=42)
        dt.fit(X_train, y_train_P)
        tr_P = accuracy_score(y_train_P, dt.predict(X_train))
        te_P = accuracy_score(y_test_P,  dt.predict(X_test))
        dt.fit(X_train, y_train_I)
        tr_I = accuracy_score(y_train_I, dt.predict(X_train))
        te_I = accuracy_score(y_test_I,  dt.predict(X_test))
        train_scores.append((tr_P + tr_I) / 2)
        test_scores.append((te_P + te_I) / 2)

    fig, ax = plt.subplots(figsize=(9, 5))
    _draw(ax, train_scores, test_scores,
          x_pos=list(range(len(depths))),
          x_labels=[str(d) for d in depths],
          xlabel="max_depth  →  complexité croissante",
          title="Decision Tree — Apprentissage vs Généralisation (Test)")
    fig.tight_layout()
    path_dt = f"{RESULTS_DIR}/curve_dt.png"
    fig.savefig(path_dt, dpi=130, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"  Courbe DT : {path_dt}")

    # ── 2. KNN — complexité croissante = k décroissant ─────────────────────
    logger.info("  Courbe complexité — KNN...")
    ks = [21, 15, 11, 9, 7, 5, 3, 1]
    train_scores, test_scores = [], []

    for k in ks:
        knn = KNeighborsClassifier(n_neighbors=k, metric="cosine", algorithm="brute")
        knn.fit(X_train, y_train_P)
        tr_P = accuracy_score(y_train_P, knn.predict(X_train))
        te_P = accuracy_score(y_test_P,  knn.predict(X_test))
        knn.fit(X_train, y_train_I)
        tr_I = accuracy_score(y_train_I, knn.predict(X_train))
        te_I = accuracy_score(y_test_I,  knn.predict(X_test))
        train_scores.append((tr_P + tr_I) / 2)
        test_scores.append((te_P + te_I) / 2)

    fig, ax = plt.subplots(figsize=(9, 5))
    _draw(ax, train_scores, test_scores,
          x_pos=list(range(len(ks))),
          x_labels=[str(k) for k in ks],
          xlabel="k (nombre de voisins)  →  complexité croissante (k décroissant)",
          title="KNN — Apprentissage vs Généralisation (Test)")
    fig.tight_layout()
    path_knn = f"{RESULTS_DIR}/curve_knn.png"
    fig.savefig(path_knn, dpi=130, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"  Courbe KNN : {path_knn}")

    # ── 3. GNB — complexité croissante = var_smoothing décroissant ─────────
    logger.info("  Courbe complexité — GaussianNB...")
    smoothings = list(reversed(list(np.logspace(-9, -1, 12))))
    train_scores, test_scores = [], []

    for vs in smoothings:
        gnb = GaussianNB(var_smoothing=vs)
        gnb.fit(X_train, y_train_P)
        tr_P = accuracy_score(y_train_P, gnb.predict(X_train))
        te_P = accuracy_score(y_test_P,  gnb.predict(X_test))
        gnb.fit(X_train, y_train_I)
        tr_I = accuracy_score(y_train_I, gnb.predict(X_train))
        te_I = accuracy_score(y_test_I,  gnb.predict(X_test))
        train_scores.append((tr_P + tr_I) / 2)
        test_scores.append((te_P + te_I) / 2)

    fig, ax = plt.subplots(figsize=(9, 5))
    _draw(ax, train_scores, test_scores,
          x_pos=list(range(len(smoothings))),
          x_labels=[f"{s:.0e}" for s in smoothings],
          xlabel="var_smoothing  →  complexité croissante (valeur décroissante)",
          title="GaussianNB — Apprentissage vs Généralisation (Test)")
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    path_gnb = f"{RESULTS_DIR}/curve_gnb.png"
    fig.savefig(path_gnb, dpi=130, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"  Courbe GNB : {path_gnb}")


def _plot_comparison(results: dict):
    """Graphique comparatif : accuracy P et I pour les 3 modèles."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    models = list(results.keys())
    acc_P = [results[m]["acc_P"] for m in models]
    acc_I = [results[m]["acc_I"] for m in models]
    f1_P  = [results[m]["f1_P"]  for m in models]
    f1_I  = [results[m]["f1_I"]  for m in models]

    x = np.arange(len(models))
    width = 0.2

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Accuracy
    ax1.bar(x - width, acc_P, width, label="Probabilité", color="steelblue")
    ax1.bar(x + width, acc_I, width, label="Impact",      color="tomato")
    ax1.set_xticks(x)
    ax1.set_xticklabels(models, fontsize=12)
    ax1.set_ylabel("Accuracy")
    ax1.set_title("Accuracy — GNB vs KNN vs DT")
    ax1.set_ylim(0, 1)
    ax1.legend()
    ax1.grid(True, axis="y", alpha=0.3)
    for i, (p, imp) in enumerate(zip(acc_P, acc_I)):
        ax1.text(i - width, p + 0.01, f"{p:.1%}", ha="center", fontsize=8)
        ax1.text(i + width, imp + 0.01, f"{imp:.1%}", ha="center", fontsize=8)

    # Macro F1
    ax2.bar(x - width, f1_P, width, label="Probabilité", color="steelblue")
    ax2.bar(x + width, f1_I, width, label="Impact",      color="tomato")
    ax2.set_xticks(x)
    ax2.set_xticklabels(models, fontsize=12)
    ax2.set_ylabel("Macro F1")
    ax2.set_title("Macro F1 — GNB vs KNN vs DT")
    ax2.set_ylim(0, 1)
    ax2.legend()
    ax2.grid(True, axis="y", alpha=0.3)
    for i, (p, imp) in enumerate(zip(f1_P, f1_I)):
        ax2.text(i - width, p + 0.01, f"{p:.3f}", ha="center", fontsize=8)
        ax2.text(i + width, imp + 0.01, f"{imp:.3f}", ha="center", fontsize=8)

    fig.tight_layout()
    path = f"{RESULTS_DIR}/benchmark_comparison.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Graphique comparatif sauvegardé : {path}")


# ── Benchmark principal ────────────────────────────────────────────────────────

def run_benchmark(models_to_run: List[str], report_path: str):
    SEP = "=" * 70

    logger.info(SEP)
    logger.info("BENCHMARK — GaussianNB vs KNN vs Decision Tree")
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
    X_test  = _encode(X_te_txt, EMBED_MODEL_NAME)

    report_lines = []
    report_lines.append(SEP)
    report_lines.append("RAPPORT DE BENCHMARK — GaussianNB vs KNN vs Decision Tree")
    report_lines.append(f"Dataset : {len(X_tr_txt)} train | {len(X_te_txt)} test")
    report_lines.append(f"Embeddings : {EMBED_MODEL_NAME} (384 dims)")
    report_lines.append(SEP)

    results = {}

    # ── GaussianNB ────────────────────────────────────────────────────────
    if "gnb" in models_to_run:
        logger.info("Entraînement GaussianNB...")
        t0 = time.time()
        gnb_P = _train_gnb(X_train, y_tr_P)
        gnb_I = _train_gnb(X_train, y_tr_I)
        elapsed = time.time() - t0
        pred_P       = gnb_P.predict(X_test).tolist()
        pred_I       = gnb_I.predict(X_test).tolist()
        pred_tr_P    = gnb_P.predict(X_train).tolist()
        pred_tr_I    = gnb_I.predict(X_train).tolist()
        report_lines.append(_fmt_table("GaussianNB", "P (Probabilité)", y_te_P, pred_P, CLASSES))
        report_lines.append(_fmt_table("GaussianNB", "I (Impact)",      y_te_I, pred_I, CLASSES))
        results["GNB"] = {
            "train_acc_P": accuracy_score(y_tr_P, pred_tr_P),
            "train_acc_I": accuracy_score(y_tr_I, pred_tr_I),
            "acc_P": accuracy_score(y_te_P, pred_P),
            "acc_I": accuracy_score(y_te_I, pred_I),
            "f1_P":  f1_score(y_te_P, pred_P, average="macro", zero_division=0),
            "f1_I":  f1_score(y_te_I, pred_I, average="macro", zero_division=0),
            "time":  elapsed,
        }

    # ── KNN ───────────────────────────────────────────────────────────────
    if "knn" in models_to_run:
        logger.info("Entraînement KNN...")
        t0 = time.time()
        knn_P = _train_knn(X_train, y_tr_P)
        knn_I = _train_knn(X_train, y_tr_I)
        elapsed = time.time() - t0
        pred_P       = knn_P.predict(X_test).tolist()
        pred_I       = knn_I.predict(X_test).tolist()
        pred_tr_P    = knn_P.predict(X_train).tolist()
        pred_tr_I    = knn_I.predict(X_train).tolist()
        report_lines.append(_fmt_table("KNN", "P (Probabilité)", y_te_P, pred_P, CLASSES))
        report_lines.append(_fmt_table("KNN", "I (Impact)",      y_te_I, pred_I, CLASSES))
        results["KNN"] = {
            "train_acc_P": accuracy_score(y_tr_P, pred_tr_P),
            "train_acc_I": accuracy_score(y_tr_I, pred_tr_I),
            "acc_P": accuracy_score(y_te_P, pred_P),
            "acc_I": accuracy_score(y_te_I, pred_I),
            "f1_P":  f1_score(y_te_P, pred_P, average="macro", zero_division=0),
            "f1_I":  f1_score(y_te_I, pred_I, average="macro", zero_division=0),
            "time":  elapsed,
        }

    # ── Decision Tree ─────────────────────────────────────────────────────
    if "dt" in models_to_run:
        logger.info("Entraînement Decision Tree...")
        t0 = time.time()
        dt_P = _train_dt(X_train, y_tr_P)
        dt_I = _train_dt(X_train, y_tr_I)
        elapsed = time.time() - t0
        pred_P       = dt_P.predict(X_test).tolist()
        pred_I       = dt_I.predict(X_test).tolist()
        pred_tr_P    = dt_P.predict(X_train).tolist()
        pred_tr_I    = dt_I.predict(X_train).tolist()
        report_lines.append(_fmt_table("Decision Tree", "P (Probabilité)", y_te_P, pred_P, CLASSES))
        report_lines.append(_fmt_table("Decision Tree", "I (Impact)",      y_te_I, pred_I, CLASSES))
        results["DT"] = {
            "train_acc_P": accuracy_score(y_tr_P, pred_tr_P),
            "train_acc_I": accuracy_score(y_tr_I, pred_tr_I),
            "acc_P": accuracy_score(y_te_P, pred_P),
            "acc_I": accuracy_score(y_te_I, pred_I),
            "f1_P":  f1_score(y_te_P, pred_P, average="macro", zero_division=0),
            "f1_I":  f1_score(y_te_I, pred_I, average="macro", zero_division=0),
            "time":  elapsed,
        }

    # ── Résumé comparatif ─────────────────────────────────────────────────
    report_lines.append(f"\n{SEP}")
    report_lines.append("RÉSUMÉ COMPARATIF")
    report_lines.append(SEP)
    report_lines.append(f"  {'Modèle':<14} {'Acc P':>7}  {'Acc I':>7}  {'F1 P':>7}  {'F1 I':>7}  {'Temps':>8}")
    report_lines.append(f"  {'──────':<14} {'─────':>7}  {'─────':>7}  {'────':>7}  {'────':>7}  {'─────':>8}")
    for name, m in results.items():
        report_lines.append(
            f"  {name:<14} {m['acc_P']:>7.1%}  {m['acc_I']:>7.1%}  "
            f"{m['f1_P']:>7.3f}  {m['f1_I']:>7.3f}  {m['time']:>7.1f}s"
        )

    # Meilleur modèle par F1 moyen
    if results:
        best = max(results, key=lambda n: (results[n]["f1_P"] + results[n]["f1_I"]) / 2)
        report_lines.append(f"\n  Meilleur modèle (Macro F1 moyen) : {best}")

    # ── Diagnostic surapprentissage ───────────────────────────────────────
    def _diag(train_acc, test_acc) -> str:
        ecart = train_acc - test_acc
        if test_acc < 0.65 and train_acc < 0.70:
            return "Sous-apprentissage ✗"
        if ecart > 0.15:
            return f"Surapprentissage   ✗  (ecart={ecart:.1%})"
        if ecart > 0.05:
            return f"Leger surapprent.  ⚠  (ecart={ecart:.1%})"
        return f"Bon apprentissage  ✓  (ecart={ecart:.1%})"

    if results:
        report_lines.append(f"\n{SEP}")
        report_lines.append("DIAGNOSTIC SURAPPRENTISSAGE / SOUS-APPRENTISSAGE")
        report_lines.append(SEP)
        report_lines.append(f"  {'Modèle':<14} {'Cible':<8} {'Train Acc':>10}  {'Test Acc':>9}  Diagnostic")
        report_lines.append(f"  {'──────':<14} {'─────':<8} {'─────────':>10}  {'────────':>9}  ──────────")
        for name, m in results.items():
            for cible, tr, te in [("P (Prob.)", m["train_acc_P"], m["acc_P"]),
                                   ("I (Impact)", m["train_acc_I"], m["acc_I"])]:
                report_lines.append(
                    f"  {name:<14} {cible:<8} {tr:>10.1%}  {te:>9.1%}  {_diag(tr, te)}"
                )
        report_lines.append("")
        report_lines.append("  Règles :")
        report_lines.append("    écart < 5%          → Bon apprentissage")
        report_lines.append("    écart 5-15%         → Léger surapprentissage")
        report_lines.append("    écart > 15%         → Surapprentissage")
        report_lines.append("    train ET test < 65% → Sous-apprentissage")

    report_lines.append(f"\n{SEP}")

    report = "\n".join(report_lines)
    for line in report_lines:
        logger.info(line)

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"\nRapport sauvegardé : {report_path}")

    # ── Courbes ───────────────────────────────────────────────────────────
    logger.info("\nGénération des courbes performance vs complexité...")
    _plot_complexity_curves(X_train, X_test, y_tr_P, y_te_P, y_tr_I, y_te_I)

    if results:
        _plot_comparison(results)

    logger.info(f"\nFichiers générés dans : {RESULTS_DIR}/")
    logger.info("  curve_dt.png           — DT : train vs test par max_depth")
    logger.info("  curve_knn.png          — KNN : train vs test par k")
    logger.info("  curve_gnb.png          — GNB : train vs test par var_smoothing")
    logger.info("  benchmark_comparison.png — Accuracy et F1 des 3 modèles")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark GaussianNB vs KNN vs Decision Tree")
    parser.add_argument("--models", nargs="+", choices=["gnb", "knn", "dt"], default=["gnb", "knn", "dt"])
    parser.add_argument("--save", default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    run_benchmark(args.models, args.save)
