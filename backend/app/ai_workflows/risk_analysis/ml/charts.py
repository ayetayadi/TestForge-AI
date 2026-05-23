"""
Génération de graphiques benchmark GNB vs KNN.
Produit 4 figures avec Accuracy, Precision, Recall, F1-Score.

Usage :
    python -m app.ai_workflows.risk_analysis.ml.charts
"""

import logging
import os
import time

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import train_test_split

from .benchmark import (
    load_data, _clean,
    _train_gnb, _train_knn,
    EMBED_MODEL_NAME, CLASSES,
)
from .nb_embed import _encode

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CHARTS_DIR = "app/ai_workflows/risk_analysis/ml/results/charts"

# ── Couleurs ───────────────────────────────────────────────────────────────────
KNN_COLOR  = "#6366f1"   # indigo
GNB_COLOR  = "#10b981"   # vert
PREC_COLOR = "#f59e0b"   # amber (precision)
REC_COLOR  = "#ef4444"   # rouge (recall)
BG         = "#f9fafb"
GRID_COLOR = "#e5e7eb"
TEXT_COLOR = "#374151"
TITLE_COLOR = "#111827"


def _apply_style(ax, title="", xlabel="", ylabel=""):
    ax.set_facecolor(BG)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#d1d5db")
    ax.spines["bottom"].set_color("#d1d5db")
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=TITLE_COLOR, fontsize=11, fontweight="bold", pad=10)
    if xlabel:
        ax.set_xlabel(xlabel, color=TEXT_COLOR, fontsize=9)
    if ylabel:
        ax.set_ylabel(ylabel, color=TEXT_COLOR, fontsize=9)


def _compute_results():
    logger.info("Chargement des données...")
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

    logger.info("Encodage SentenceTransformer...")
    X_train = _encode(X_tr_txt, EMBED_MODEL_NAME)
    X_test = _encode(X_te_txt, EMBED_MODEL_NAME)

    results = {}

    for model_name, train_fn in [("GaussianNB", _train_gnb), ("KNN", _train_knn)]:
        logger.info(f"Entraînement {model_name}...")
        entry = {}
        for target, y_tr, y_te in [("P", y_tr_P, y_te_P), ("I", y_tr_I, y_te_I)]:
            model = train_fn(X_train, y_tr)
            y_pred = model.predict(X_test).tolist()

            report = classification_report(
                y_te, y_pred, labels=CLASSES, output_dict=True, zero_division=0,
            )
            per_class = {
                c: {
                    "precision": report[str(c)]["precision"],
                    "recall":    report[str(c)]["recall"],
                    "f1":        report[str(c)]["f1-score"],
                }
                for c in CLASSES if str(c) in report
            }

            entry[target] = {
                "accuracy":    accuracy_score(y_te, y_pred),
                "precision":   report["weighted avg"]["precision"],
                "recall":      report["weighted avg"]["recall"],
                "f1":          report["weighted avg"]["f1-score"],
                "per_class":   per_class,
                "y_te":        y_te,
                "y_pred":      y_pred,
            }
            logger.info(f"  {model_name} {target} → Acc={entry[target]['accuracy']:.3f} | F1={entry[target]['f1']:.3f}")

        results[model_name] = entry

    return results


# ── Figure 1 : Accuracy + F1 (barres groupées) ────────────────────────────────

def _plot_accuracy_f1(results: dict, save_path: str):
    metrics = [("Accuracy", "accuracy"), ("F1-Score", "f1")]
    targets = ["P", "I"]
    models = ["GaussianNB", "KNN"]
    colors = {"GaussianNB": GNB_COLOR, "KNN": KNN_COLOR}

    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    fig.patch.set_facecolor(BG)
    fig.suptitle("Accuracy & F1-Score — GaussianNB vs KNN",
                 color=TITLE_COLOR, fontsize=13, fontweight="bold", y=1.02)

    x = np.arange(len(models))
    width = 0.35

    for ax, (label, key) in zip(axes, metrics):
        for i, target in enumerate(targets):
            vals = [results[m][target][key] for m in models]
            offset = (i - 0.5) * width
            color = KNN_COLOR if target == "P" else GNB_COLOR
            bars = ax.bar(x + offset, vals, width, color=color, alpha=0.85,
                          zorder=3, label=f"{target} (Probabilité)" if target == "P" else f"{target} (Impact)",
                          edgecolor="white", linewidth=0.8)
            for bar, v in zip(bars, vals):
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                        f"{v:.3f}", ha="center", va="bottom", fontsize=9,
                        color=TITLE_COLOR, fontweight="bold")

        _apply_style(ax, title=label, ylabel=label)
        ax.set_xticks(x)
        ax.set_xticklabels(models, fontsize=10)
        ax.set_ylim(0.4, 1.05)
        ax.legend(fontsize=8, framealpha=0.6, facecolor=BG, edgecolor=GRID_COLOR)

    plt.tight_layout()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    logger.info(f"Sauvegardé : {save_path}")


# ── Figure 2 : Precision & Recall (barres groupées) ───────────────────────────

def _plot_precision_recall_bars(results: dict, save_path: str):
    targets = ["P", "I"]
    models = ["GaussianNB", "KNN"]

    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    fig.patch.set_facecolor(BG)
    fig.suptitle("Precision & Recall — GaussianNB vs KNN",
                 color=TITLE_COLOR, fontsize=13, fontweight="bold", y=1.02)

    x = np.arange(len(models))
    width = 0.35

    for ax, target in zip(axes, targets):
        prec_vals = [results[m][target]["precision"] for m in models]
        rec_vals  = [results[m][target]["recall"] for m in models]

        bars1 = ax.bar(x - width/2, prec_vals, width, color=PREC_COLOR, alpha=0.85,
                       zorder=3, label="Precision", edgecolor="white", linewidth=0.8)
        bars2 = ax.bar(x + width/2, rec_vals, width, color=REC_COLOR, alpha=0.85,
                       zorder=3, label="Recall", edgecolor="white", linewidth=0.8)

        for bar, v in zip(bars1, prec_vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                    f"{v:.3f}", ha="center", va="bottom", fontsize=9,
                    color=TITLE_COLOR, fontweight="bold")
        for bar, v in zip(bars2, rec_vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                    f"{v:.3f}", ha="center", va="bottom", fontsize=9,
                    color=TITLE_COLOR, fontweight="bold")

        _apply_style(ax, title=f"{'Probabilité (P)' if target == 'P' else 'Impact (I)'}")
        ax.set_xticks(x)
        ax.set_xticklabels(models, fontsize=10)
        ax.set_ylim(0.4, 1.05)
        ax.legend(fontsize=8, framealpha=0.6, facecolor=BG, edgecolor=GRID_COLOR)

    plt.tight_layout()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    logger.info(f"Sauvegardé : {save_path}")


# ── Figure 3 : F1 par classe (courbes) ────────────────────────────────────────

def _plot_f1_per_class(results: dict, save_path: str):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    fig.patch.set_facecolor(BG)
    fig.suptitle("F1-Score par classe — GaussianNB vs KNN",
                 color=TITLE_COLOR, fontsize=13, fontweight="bold", y=1.02)

    styles = {"GaussianNB": ("o", "-", GNB_COLOR), "KNN": ("s", "--", KNN_COLOR)}

    for ax, target in zip(axes, ["P", "I"]):
        for model, (marker, ls, color) in styles.items():
            f1s = [results[model][target]["per_class"].get(c, {}).get("f1", 0) for c in CLASSES]
            ax.plot(CLASSES, f1s, marker=marker, linestyle=ls, color=color,
                    linewidth=2.2, markersize=7, label=model, zorder=3)
            for c, v in zip(CLASSES, f1s):
                ax.annotate(f"{v:.2f}", (c, v), textcoords="offset points",
                            xytext=(0, 9), ha="center", fontsize=7.5, color=color, fontweight="bold")

        _apply_style(ax,
                     title=f"{'Probabilité (P)' if target == 'P' else 'Impact (I)'}",
                     xlabel="Classe (1 = faible → 5 = élevé)", ylabel="F1-Score")
        ax.set_xticks(CLASSES)
        ax.set_ylim(0.3, 1.05)
        ax.legend(fontsize=9, framealpha=0.6, facecolor=BG, edgecolor=GRID_COLOR)
        ax.axhline(0.80, color=GRID_COLOR, linewidth=1, linestyle=":", zorder=1)

    plt.tight_layout()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    logger.info(f"Sauvegardé : {save_path}")


# ── Figure 4 : Precision & Recall par classe (courbes) ────────────────────────

def _plot_precision_recall_per_class(results: dict, save_path: str):
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    fig.patch.set_facecolor(BG)
    fig.suptitle("Precision & Recall par classe — GaussianNB vs KNN",
                 color=TITLE_COLOR, fontsize=13, fontweight="bold", y=1.01)

    for col, model in enumerate(["GaussianNB", "KNN"]):
        color = GNB_COLOR if model == "GaussianNB" else KNN_COLOR
        for row, target in enumerate(["P", "I"]):
            ax = axes[row][col]
            pc = results[model][target]["per_class"]

            prec = [pc.get(c, {}).get("precision", 0) for c in CLASSES]
            rec  = [pc.get(c, {}).get("recall", 0) for c in CLASSES]

            ax.plot(CLASSES, prec, marker="o", linestyle="-", color=color,
                    linewidth=2, markersize=6, label="Precision", zorder=3)
            ax.plot(CLASSES, rec, marker="^", linestyle="--", color=REC_COLOR,
                    linewidth=2, markersize=6, label="Recall", zorder=3)
            ax.fill_between(CLASSES, prec, rec, alpha=0.08, color=color)

            _apply_style(ax,
                         title=f"{model} — {'Probabilité (P)' if target == 'P' else 'Impact (I)'}",
                         xlabel="Classe", ylabel="Score")
            ax.set_xticks(CLASSES)
            ax.set_ylim(0.3, 1.1)
            ax.legend(fontsize=8, framealpha=0.6, facecolor=BG, edgecolor=GRID_COLOR)
            ax.axhline(0.80, color=GRID_COLOR, linewidth=1, linestyle=":", zorder=1)

    plt.tight_layout()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    logger.info(f"Sauvegardé : {save_path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("GÉNÉRATION DES GRAPHIQUES — GaussianNB vs KNN")
    logger.info("=" * 60)

    results = _compute_results()
    os.makedirs(CHARTS_DIR, exist_ok=True)

    _plot_accuracy_f1(results,              f"{CHARTS_DIR}/accuracy_f1.png")
    _plot_precision_recall_bars(results,    f"{CHARTS_DIR}/precision_recall_bars.png")
    _plot_f1_per_class(results,             f"{CHARTS_DIR}/f1_per_class.png")
    _plot_precision_recall_per_class(results, f"{CHARTS_DIR}/precision_recall_per_class.png")

    logger.info("=" * 60)
    logger.info(f"4 graphiques sauvegardés dans : {CHARTS_DIR}/")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()