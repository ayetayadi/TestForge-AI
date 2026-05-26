"""
Benchmark KNN pour Risk Analysis — 5 classes (Probabilité et Impact).

Étapes :
  1. Chargement et nettoyage du dataset
  2. Encodage SentenceTransformer (384 dims)
  3. Split stratifié 80% train / 20% test
  4. Sélection de k par GridSearchCV + StratifiedKFold 5 folds (scoring=f1_macro)
  5. Évaluation finale sur le test 20% (Accuracy, Precision, Recall, F1 par classe)
  6. Génération de l'image knn_evaluation.png

Usage :
    python -m app.ai_workflows.risk_analysis.ml.benchmark
"""

import logging
import os
import sys
import re
import time

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.neighbors import KNeighborsClassifier

from .config import EMBED_MODEL_NAME
from .nb_embed import _encode

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DATASET_PATH  = "data/risk_dataset.xlsx"
FEEDBACK_PATH = "data/risk_feedback.xlsx"
RESULTS_DIR   = "app/ai_workflows/risk_analysis/ml/results"
REPORT_PATH   = f"{RESULTS_DIR}/benchmark_report.txt"

COLUMN_ALIASES = {
    "user_story":          ["user story", "user_story", "us", "story", "histoire utilisateur"],
    "acceptance_criteria": ["acceptance criteria", "acceptance_criteria", "ac",
                            "criteres d'acceptation", "criteres acceptation",
                            "criteres_acceptation", "criteres_acceptation"],
    "probability":         ["probability", "probabilite", "probabilite", "prob", "p"],
    "impact":              ["impact", "i"],
}

CLASSES = [1, 2, 3, 4, 5]
SEP     = "=" * 65


# ── Utilitaires ───────────────────────────────────────────────────────────────

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


def _load_data() -> pd.DataFrame:
    if not os.path.exists(DATASET_PATH):
        logger.error(f"Dataset introuvable : {DATASET_PATH}")
        sys.exit(1)
    df = pd.read_excel(DATASET_PATH)
    df = _normalize_columns(df)
    if os.path.exists(FEEDBACK_PATH):
        fb = pd.read_excel(FEEDBACK_PATH)
        fb = _normalize_columns(fb)
        if "corrected_probability" in fb.columns:
            fb = fb.rename(columns={"corrected_probability": "probability",
                                    "corrected_impact": "impact"})
        df = pd.concat([df, fb], ignore_index=True)
    return df


# ── Entraînement KNN ──────────────────────────────────────────────────────────

def _train_knn(X_train, y_train, label: str):
    """
    Sélectionne k optimal par GridSearchCV (5-fold stratifié, scoring=f1_macro).
    weights='uniform' : vote majoritaire simple — pas d'artefact sur le train.
    """
    param_grid = {"n_neighbors": [3, 5, 7, 11]}
    grid = GridSearchCV(
        KNeighborsClassifier(weights="uniform", metric="cosine", algorithm="brute"),
        param_grid=param_grid,
        cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=42),
        scoring="f1_macro",
        n_jobs=-1,
    )
    grid.fit(X_train, y_train)
    best_k  = grid.best_params_["n_neighbors"]
    cv_f1   = grid.best_score_
    logger.info(f"  {label} → k={best_k} | CV F1 macro = {cv_f1:.3f}")
    return grid.best_estimator_, best_k, cv_f1


# ── Rapport texte ─────────────────────────────────────────────────────────────

def _fmt_metrics(y_true, y_pred, target: str) -> list:
    lines = []
    lines.append(f"\n{'─'*65}")
    lines.append(f"  Cible : {target}")
    lines.append(f"{'─'*65}")

    acc      = accuracy_score(y_true, y_pred)
    macro_f1 = f1_score(y_true, y_pred, average="macro", zero_division=0)
    report   = classification_report(y_true, y_pred, labels=CLASSES,
                                     output_dict=True, zero_division=0)

    lines.append(f"  Accuracy  : {acc:.4f}  ({acc:.1%})")
    lines.append(f"  Macro F1  : {macro_f1:.4f}")
    lines.append("")
    lines.append(f"  {'Classe':>7}  {'Precision':>10}  {'Recall':>8}  "
                 f"{'F1-Score':>10}  {'Support':>8}")
    lines.append(f"  {'-------':>7}  {'----------':>10}  {'--------':>8}  "
                 f"{'----------':>10}  {'-------':>8}")
    for c in CLASSES:
        r = report[str(c)]
        lines.append(
            f"  {c:>7}  {r['precision']:>10.4f}  {r['recall']:>8.4f}  "
            f"{r['f1-score']:>10.4f}  {int(r['support']):>8d}"
        )
    lines.append(f"\n  Macro avg  Precision={report['macro avg']['precision']:.4f}  "
                 f"Recall={report['macro avg']['recall']:.4f}  F1={macro_f1:.4f}")
    return lines


def _diag(cv_f1: float, test_f1: float) -> str:
    ecart = test_f1 - cv_f1
    if cv_f1 < 0.65 and test_f1 < 0.65:
        return f"Sous-apprentissage  (ecart={ecart:+.1%})"
    if ecart < -0.10:
        return f"Surapprentissage    (ecart={ecart:+.1%})"
    if ecart < -0.05:
        return f"Leger surapprentissage  (ecart={ecart:+.1%})"
    return f"Bon apprentissage   (ecart={ecart:+.1%})"


# ── Image d'évaluation ────────────────────────────────────────────────────────

def _plot_knn_evaluation(model_P, model_I, X_test, y_test_P, y_test_I):
    """
    Image knn_evaluation.png : 2 subplots côte à côte.
      - Gauche : Probabilité (P) — test 20%
      - Droite : Impact (I)      — test 20%
    Chaque subplot montre 4 métriques globales (Accuracy, Macro Precision,
    Macro Recall, Macro F1), sans détail par classe pour éviter les 1.0 isolés.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib non installe — image ignoree")
        return

    def _global_metrics(model, X, y_true):
        y_pred  = model.predict(X).tolist()
        report  = classification_report(y_true, y_pred, labels=CLASSES,
                                        output_dict=True, zero_division=0)
        acc     = accuracy_score(y_true, y_pred)
        m_prec  = report["macro avg"]["precision"]
        m_rec   = report["macro avg"]["recall"]
        m_f1    = report["macro avg"]["f1-score"]
        return acc, m_prec, m_rec, m_f1

    configs = [
        ("Probabilité (P) — Test",  model_P, y_test_P),
        ("Impact (I) — Test",       model_I, y_test_I),
    ]

    metric_labels = ["Accuracy", "Macro\nPrecision", "Macro\nRecall", "Macro\nF1"]
    colors        = ["#3498db", "#e67e22", "#9b59b6", "#2ecc71"]
    x             = np.arange(len(metric_labels))
    width         = 0.5

    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    fig.suptitle(
        f"KNN — Évaluation globale sur le jeu de test (20%)\n"
        f"weights=uniform | metric=cosine | embeddings={EMBED_MODEL_NAME.split('/')[-1]}",
        fontsize=12, fontweight="bold",
    )

    for ax, (title, model, y_true) in zip(axes, configs):
        acc, m_prec, m_rec, m_f1 = _global_metrics(model, X_test, y_true)
        values = [acc, m_prec, m_rec, m_f1]

        bars = ax.bar(x, values, width, color=colors, alpha=0.85, edgecolor="white")

        ax.set_xticks(x)
        ax.set_xticklabels(metric_labels, fontsize=11)
        ax.set_ylim(0, 1.15)
        ax.set_ylabel("Score", fontsize=11)
        ax.set_title(
            f"{title}\nAccuracy = {acc:.3f}  |  Macro F1 = {m_f1:.3f}",
            fontsize=11, fontweight="bold", color="#2c3e50",
        )
        ax.axhline(y=0.80, color="#e74c3c", linestyle="--", linewidth=1,
                   alpha=0.6, label="Seuil 0.80")
        ax.legend(fontsize=9, loc="lower right")
        ax.grid(True, axis="y", alpha=0.3)

        for bar, val in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, val + 0.012,
                    f"{val:.3f}", ha="center", va="bottom",
                    fontsize=11, fontweight="bold")

    fig.tight_layout()
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = f"{RESULTS_DIR}/knn_evaluation.png"
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Image sauvegardee : {path}")
    return path


# ── Courbe complexité KNN ─────────────────────────────────────────────────────

def _plot_knn_curve(X_train, y_train_P, y_train_I):
    """
    Courbe accuracy (moyenne P+I) en fonction de k pour train et test.
    Permet de visualiser la zone de bon apprentissage.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    from sklearn.model_selection import cross_val_score

    # k décroissant = complexité croissante de gauche à droite
    ks = [21, 15, 11, 9, 7, 5, 3, 1]
    train_errors, cv_errors = [], []

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    for k in ks:
        knn = KNeighborsClassifier(n_neighbors=k, weights="uniform",
                                   metric="cosine", algorithm="brute")
        # Erreur train (1 - accuracy, moyenne P et I)
        knn.fit(X_train, y_train_P)
        tr_P = 1 - accuracy_score(y_train_P, knn.predict(X_train))
        knn.fit(X_train, y_train_I)
        tr_I = 1 - accuracy_score(y_train_I, knn.predict(X_train))
        train_errors.append((tr_P + tr_I) / 2)

        # Erreur CV (5-fold, moyenne P et I)
        cv_P = 1 - cross_val_score(
            KNeighborsClassifier(n_neighbors=k, weights="uniform",
                                 metric="cosine", algorithm="brute"),
            X_train, y_train_P, cv=cv, scoring="accuracy", n_jobs=-1
        ).mean()
        cv_I = 1 - cross_val_score(
            KNeighborsClassifier(n_neighbors=k, weights="uniform",
                                 metric="cosine", algorithm="brute"),
            X_train, y_train_I, cv=cv, scoring="accuracy", n_jobs=-1
        ).mean()
        cv_errors.append((cv_P + cv_I) / 2)

    x_pos = list(range(len(ks)))

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x_pos, train_errors, "o-",  color="steelblue", linewidth=2,
            label="Erreur Train")
    ax.plot(x_pos, cv_errors,    "s--", color="tomato",    linewidth=2,
            label="Erreur Validation croisée")

    # Zones
    idx3 = ks.index(3)
    n = len(ks)
    ax.axvspan(0,       2.5,     alpha=0.07, color="orange", label="Sous-apprentissage")
    ax.axvspan(2.5,     6.5,     alpha=0.07, color="green",  label="Zone optimale")
    ax.axvspan(6.5,     n - 0.5, alpha=0.07, color="red",    label="Sur-apprentissage")

    # Annoter k=3
    ax.axvline(x=idx3, color="#27ae60", linestyle=":", linewidth=1.8, alpha=0.9)
    ax.annotate(f"k=3 retenu",
                xy=(idx3, cv_errors[idx3]),
                xytext=(idx3 + 0.5, cv_errors[idx3] + 0.015),
                fontsize=9, color="#27ae60",
                arrowprops=dict(arrowstyle="->", color="#27ae60", lw=1.2))

    ax.set_xticks(x_pos)
    ax.set_xticklabels([f"k={k}" for k in ks], fontsize=10)
    ax.set_xlabel("Complexité du modèle  (k décroissant → complexité croissante)", fontsize=11)
    ax.set_ylabel("Erreur moyenne (1 - Accuracy)", fontsize=11)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.3)
    ax.set_title("KNN — Courbe biais-variance\n"
                 "Sous-apprentissage → Zone optimale → Sur-apprentissage",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=9, loc="upper center")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = f"{RESULTS_DIR}/curve_knn.png"
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Courbe KNN sauvegardee : {path}")


# ── Benchmark principal ────────────────────────────────────────────────────────

def run_benchmark():
    logger.info(SEP)
    logger.info("BENCHMARK KNN — Risk Analysis (5 classes)")
    logger.info(SEP)

    # ── Étape 1 : Chargement des données ──────────────────────────────────
    logger.info("Etape 1 : Chargement du dataset...")
    df = _load_data()
    df["user_story"]         = df["user_story"].apply(_clean)
    df["acceptance_criteria"] = df["acceptance_criteria"].apply(_clean)
    df["text"] = df["user_story"] + " " + df["acceptance_criteria"].fillna("")

    texts = df["text"].tolist()
    y_P   = df["probability"].astype(int).tolist()
    y_I   = df["impact"].astype(int).tolist()
    logger.info(f"  Total exemples : {len(texts)}")

    # ── Étape 2 : Split 80/20 stratifié ───────────────────────────────────
    logger.info("Etape 2 : Split stratifie 80% train / 20% test...")
    X_tr_txt, X_te_txt, y_tr_P, y_te_P, y_tr_I, y_te_I = train_test_split(
        texts, y_P, y_I, test_size=0.2, random_state=42, stratify=y_P,
    )
    logger.info(f"  Train : {len(X_tr_txt)} exemples | Test : {len(X_te_txt)} exemples")

    # ── Étape 3 : Encodage SentenceTransformer ─────────────────────────────
    logger.info("Etape 3 : Encodage SentenceTransformer...")
    logger.info(f"  Modele : {EMBED_MODEL_NAME}")
    X_train = _encode(X_tr_txt, EMBED_MODEL_NAME)
    X_test  = _encode(X_te_txt, EMBED_MODEL_NAME)
    logger.info(f"  Dimensions vecteurs : {X_train.shape[1]}")

    # ── Étape 4 : GridSearchCV pour k ─────────────────────────────────────
    logger.info("Etape 4 : Selection de k par GridSearchCV (5-fold, f1_macro)...")
    logger.info("  Valeurs testees : k = [3, 5, 7, 11] | weights=uniform")
    t0 = time.time()
    knn_P, best_k_P, cv_f1_P = _train_knn(X_train, y_tr_P, "Probabilite (P)")
    knn_I, best_k_I, cv_f1_I = _train_knn(X_train, y_tr_I, "Impact (I)")
    elapsed = time.time() - t0
    logger.info(f"  Temps total : {elapsed:.1f}s")

    # ── Étape 5 : Prédictions sur le test ─────────────────────────────────
    logger.info("Etape 5 : Evaluation sur le jeu de test (20%)...")
    pred_P = knn_P.predict(X_test).tolist()
    pred_I = knn_I.predict(X_test).tolist()

    test_f1_P = f1_score(y_te_P, pred_P, average="macro", zero_division=0)
    test_f1_I = f1_score(y_te_I, pred_I, average="macro", zero_division=0)

    # ── Rapport ────────────────────────────────────────────────────────────
    lines = []
    lines.append(SEP)
    lines.append("RAPPORT KNN — Risk Analysis (5 classes)")
    lines.append(SEP)
    lines.append(f"  Dataset          : {len(texts)} exemples")
    lines.append(f"  Train            : {len(X_tr_txt)} exemples (80%)")
    lines.append(f"  Test             : {len(X_te_txt)} exemples (20%)")
    lines.append(f"  Embeddings       : {EMBED_MODEL_NAME}")
    lines.append(f"  Dimensions       : {X_train.shape[1]}")
    lines.append(f"  Modele           : KNN (weights=uniform, metric=cosine)")
    lines.append(f"  Selection k      : GridSearchCV 5-fold, scoring=f1_macro")
    lines.append(f"  Temps entrainement : {elapsed:.1f}s")
    lines.append("")
    lines.append(f"  k retenu — Probabilite : k={best_k_P}  (CV F1={cv_f1_P:.3f})")
    lines.append(f"  k retenu — Impact      : k={best_k_I}  (CV F1={cv_f1_I:.3f})")

    lines += _fmt_metrics(y_te_P, pred_P, "Probabilite (P) — Test 20%")
    lines += _fmt_metrics(y_te_I, pred_I, "Impact (I) — Test 20%")

    lines.append(f"\n{SEP}")
    lines.append("DIAGNOSTIC GENERALISATION (CV F1 vs Test F1)")
    lines.append(SEP)
    lines.append(f"  {'Cible':<18} {'CV F1':>7}  {'Test F1':>8}  {'Diagnostic'}")
    lines.append(f"  {'─────':<18} {'─────':>7}  {'───────':>8}  {'──────────'}")
    lines.append(f"  {'Probabilite (P)':<18} {cv_f1_P:>7.3f}  {test_f1_P:>8.3f}  {_diag(cv_f1_P, test_f1_P)}")
    lines.append(f"  {'Impact (I)':<18} {cv_f1_I:>7.3f}  {test_f1_I:>8.3f}  {_diag(cv_f1_I, test_f1_I)}")
    lines.append("")
    lines.append("  Regles (ecart = Test F1 - CV F1) :")
    lines.append("    ecart > -5%      -> Bon apprentissage")
    lines.append("    ecart -5 a -10%  -> Leger surapprentissage")
    lines.append("    ecart < -10%     -> Surapprentissage")
    lines.append("    CV et Test < 0.65 -> Sous-apprentissage")
    lines.append(SEP)

    for line in lines:
        logger.info(line)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"\nRapport sauvegarde : {REPORT_PATH}")

    # ── Étape 6 : Images ──────────────────────────────────────────────────
    logger.info("\nEtape 6 : Generation des images...")
    _plot_knn_evaluation(knn_P, knn_I, X_test, y_te_P, y_te_I)
    _plot_knn_curve(X_train, y_tr_P, y_tr_I)

    logger.info(f"\nFichiers generes dans : {RESULTS_DIR}/")
    logger.info("  knn_evaluation.png — Precision/Recall/F1 par classe (P et I, test 20%)")
    logger.info("  curve_knn.png      — Courbe train vs test selon k")
    logger.info(f"  benchmark_report.txt")


if __name__ == "__main__":
    run_benchmark()
