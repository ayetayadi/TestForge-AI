"""
plot_results.py — Visualisation du benchmark LLM (Axe 1 : Performance)

Génère des graphiques comparatifs style HumanEval pour le rapport PFE.

Lancement :
  cd backend
  python -m app.ai_workflows.user_story_refinement.evaluation.plot_results

  # Ou sur un fichier spécifique :
  python -m app.ai_workflows.user_story_refinement.evaluation.plot_results \
      --file app/ai_workflows/user_story_refinement/evaluation/results/benchmark_llm_20260517_041715.json

Sortie : dossier results/charts/ avec 6 PNG haute résolution.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")   # pas de fenêtre GUI — génère directement en PNG
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── Palette professionnelle (rapport PFE) ────────────────────────────────────
COLORS = [
    "#2563EB",   # bleu vif
    "#16A34A",   # vert
    "#DC2626",   # rouge
    "#D97706",   # orange
    "#7C3AED",   # violet
    "#0891B2",   # cyan
]

# Couleurs par catégorie de story
CAT_COLORS = {"bad": "#DC2626", "medium": "#D97706", "good": "#16A34A"}

STYLE = {
    "figure.facecolor": "white",
    "axes.facecolor":   "#F8FAFC",
    "axes.grid":        True,
    "grid.color":       "#E2E8F0",
    "grid.linewidth":   0.8,
    "axes.spines.top":  False,
    "axes.spines.right":False,
    "font.family":      "DejaVu Sans",
    "font.size":        11,
    "axes.titlesize":   13,
    "axes.titleweight": "bold",
    "axes.labelsize":   11,
}

plt.rcParams.update(STYLE)

RESULTS_DIR = Path(__file__).parent / "results"
CHARTS_DIR  = RESULTS_DIR / "charts"


# ─────────────────────────────────────────────────────────────────────────────
# CHARGEMENT DES DONNÉES
# ─────────────────────────────────────────────────────────────────────────────

def _load_latest(path: Path | None) -> Dict[str, Any]:
    """Charge le dernier fichier JSON de results/ ou le fichier spécifié."""
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    files = sorted(RESULTS_DIR.glob("benchmark_llm_*.json"))
    if not files:
        print("[ERROR] Aucun fichier de résultats trouvé dans", RESULTS_DIR)
        sys.exit(1)
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# GRAPHIQUE 1 — Score composite (classement général)
# ─────────────────────────────────────────────────────────────────────────────

def plot_composite_ranking(ranking: List[Dict], out: Path) -> None:
    """
    Bar chart horizontal du score composite, style HumanEval leaderboard.
    Chaque barre montre le score global du modèle.
    """
    models    = [r["model"] for r in ranking]
    scores    = [r.get("composite", 0) for r in ranking]
    colors    = [COLORS[i % len(COLORS)] for i in range(len(models))]

    fig, ax = plt.subplots(figsize=(10, max(4, len(models) * 1.1)))
    bars = ax.barh(models[::-1], scores[::-1], color=colors[::-1],
                   height=0.55, edgecolor="white", linewidth=1.2)

    # Valeurs sur les barres
    for bar, score in zip(bars, scores[::-1]):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{score:.1f}", va="center", fontweight="bold", fontsize=11)

    ax.set_xlim(0, max(scores) * 1.25 if scores else 100)
    ax.set_xlabel("Score composite (higher is better)")
    ax.set_title("Axe 1 — Classement général des modèles LLM\n"
                 "Score composite = GEval×40 + Δrule×25 + amélioration×0.15 + succès×0.10 − violation×0.05 − latence×1")
    ax.tick_params(axis="y", labelsize=11)

    # Badge rang
    for i, (bar, r) in enumerate(zip(bars, ranking[::-1])):
        rank_label = f"#{r['rank']}"
        ax.text(0.5, bar.get_y() + bar.get_height() / 2,
                rank_label, va="center", ha="left",
                color="white", fontweight="bold", fontsize=10)

    fig.tight_layout()
    fig.savefig(out / "01_composite_ranking.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print("  [OK] 01_composite_ranking.png")


# ─────────────────────────────────────────────────────────────────────────────
# GRAPHIQUE 2 — Radar chart multi-métriques
# ─────────────────────────────────────────────────────────────────────────────

def plot_radar(ranking: List[Dict], out: Path) -> None:
    """
    Spider/radar chart : 5 dimensions clés par modèle.
    Style typique des benchmarks de recherche.
    """
    dims = [
        ("Succès %",       "success_rate_%",      100),
        ("Amélioration %", "improvement_rate_%",   100),
        ("Score Δ ×100",   "score_delta_mean",       1),
        ("Sans violation", "violation_rate_%",      100),  # inversé
        ("Rapidité",       "latency_mean_s",         10),  # inversé
    ]
    labels = [d[0] for d in dims]
    N = len(labels)

    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]   # fermer le polygone

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw={"polar": True})
    ax.set_facecolor("#F8FAFC")

    for i, r in enumerate(ranking):
        values = []
        for _, key, scale in dims:
            val = r.get(key, 0) or 0
            if key == "score_delta_mean":
                val = val * 100          # 0..1 → 0..100
            elif key == "violation_rate_%":
                val = 100 - val          # inverser : moins de violation = mieux
            elif key == "latency_mean_s":
                # inverser : moins de latence = mieux, normalisé 0..100
                val = max(0, 100 - val * 10)
            values.append(min(100, max(0, val)))
        values += values[:1]

        color = COLORS[i % len(COLORS)]
        ax.plot(angles, values, color=color, linewidth=2.2, linestyle="solid")
        ax.fill(angles, values, color=color, alpha=0.15)
        ax.scatter(angles[:-1], values[:-1], color=color, s=60, zorder=5)

    # Axes et labels
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, size=11)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], size=8, color="#94A3B8")
    ax.set_ylim(0, 100)
    ax.spines["polar"].set_color("#CBD5E1")

    legend_patches = [
        mpatches.Patch(color=COLORS[i % len(COLORS)], label=r["model"])
        for i, r in enumerate(ranking)
    ]
    ax.legend(handles=legend_patches, loc="upper right",
              bbox_to_anchor=(1.35, 1.15), framealpha=0.9)

    ax.set_title("Axe 1 — Profil multi-dimensionnel des modèles\n"
                 "(normalisé 0–100, plus haut = meilleur)",
                 pad=20, fontsize=13, fontweight="bold")

    fig.tight_layout()
    fig.savefig(out / "02_radar_chart.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] 02_radar_chart.png")


# ─────────────────────────────────────────────────────────────────────────────
# GRAPHIQUE 3 — Score initial vs final par story (scatter)
# ─────────────────────────────────────────────────────────────────────────────

def plot_score_progression(raw_results: Dict[str, List], out: Path) -> None:
    """
    Scatter plot : score initial vs final pour chaque story.
    Couleur = catégorie (bad/medium/good). Ligne diagonale = pas d'amélioration.
    """
    fig, axes = plt.subplots(1, len(raw_results),
                              figsize=(6 * len(raw_results), 5.5),
                              squeeze=False)

    for col, (model_name, stories) in enumerate(raw_results.items()):
        ax = axes[0][col]
        for s in stories:
            cat   = s.get("category", "medium")
            color = CAT_COLORS.get(cat, "#64748B")
            ax.scatter(s["initial_score"], s["final_score"],
                       color=color, s=90, zorder=3, edgecolors="white", linewidth=0.8)
            ax.annotate(s["story_id"],
                        (s["initial_score"], s["final_score"]),
                        textcoords="offset points", xytext=(4, 4),
                        fontsize=7, color="#475569")

        # Diagonale = pas d'amélioration
        lims = [0, 1]
        ax.plot(lims, lims, "--", color="#94A3B8", linewidth=1.2, label="Pas de changement")
        ax.set_xlim(0, 1.05)
        ax.set_ylim(0, 1.05)
        ax.set_xlabel("Score initial (avant LLM)")
        ax.set_ylabel("Score final (après LLM)")
        ax.set_title(f"{model_name}\nScore initial → final par story")

        legend_patches = [
            mpatches.Patch(color=c, label=cat.capitalize())
            for cat, c in CAT_COLORS.items()
        ]
        ax.legend(handles=legend_patches, fontsize=9)

    fig.suptitle("Axe 1 — Amélioration du score INVEST par story\n"
                 "(points au-dessus de la diagonale = améliorés par le LLM)",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(out / "03_score_progression.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] 03_score_progression.png")


# ─────────────────────────────────────────────────────────────────────────────
# GRAPHIQUE 4 — Heatmap Δscore (stories × modèles)
# ─────────────────────────────────────────────────────────────────────────────

def plot_delta_heatmap(raw_results: Dict[str, List], out: Path) -> None:
    """
    Heatmap : ligne = story, colonne = modèle, cellule = score_delta.
    Permet de voir quelles stories bénéficient le plus de quel modèle.
    """
    models  = list(raw_results.keys())
    if not models:
        return

    story_ids = [s["story_id"] for s in raw_results[models[0]]]
    matrix    = np.zeros((len(story_ids), len(models)))

    for col, model in enumerate(models):
        story_map = {s["story_id"]: s for s in raw_results[model]}
        for row, sid in enumerate(story_ids):
            s = story_map.get(sid)
            matrix[row, col] = s["score_delta"] if s else 0.0

    fig, ax = plt.subplots(figsize=(max(7, len(models) * 2), len(story_ids) * 0.6 + 2))

    # Colormap : rouge = régression, blanc = stable, vert = amélioration
    cmap = plt.cm.RdYlGn
    im   = ax.imshow(matrix, cmap=cmap, vmin=-0.3, vmax=0.9, aspect="auto")

    # Labels
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels(models, rotation=30, ha="right", fontsize=10)
    ax.set_yticks(range(len(story_ids)))
    ax.set_yticklabels(story_ids, fontsize=9)

    # Valeurs dans les cellules
    for row in range(len(story_ids)):
        for col in range(len(models)):
            val = matrix[row, col]
            color = "white" if abs(val) > 0.4 else "#1E293B"
            ax.text(col, row, f"{val:+.2f}", ha="center", va="center",
                    fontsize=9, color=color, fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.set_label("Δscore (final − initial)", fontsize=10)

    ax.set_title("Axe 1 — Heatmap Δscore INVEST par story et par modèle\n"
                 "(vert = amélioration, rouge = régression)", fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "04_delta_heatmap.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] 04_delta_heatmap.png")


# ─────────────────────────────────────────────────────────────────────────────
# GRAPHIQUE 5 — Latence par modèle (bar + p95)
# ─────────────────────────────────────────────────────────────────────────────

def plot_latency(ranking: List[Dict], raw_results: Dict[str, List], out: Path) -> None:
    """
    Bar chart de latence moyenne + barre d'erreur pour p95.
    Référence sur les 5 modèles pour le rapport PFE.
    """
    models    = [r["model"] for r in ranking]
    lat_mean  = [r.get("latency_mean_s", 0) for r in ranking]
    lat_p95   = [r.get("latency_p95_s", 0) for r in ranking]
    lat_min   = [r.get("latency_min_s", 0) for r in ranking]
    colors    = [COLORS[i % len(COLORS)] for i in range(len(models))]

    fig, ax = plt.subplots(figsize=(max(8, len(models) * 1.8), 5))
    x = np.arange(len(models))
    w = 0.5

    bars = ax.bar(x, lat_mean, width=w, color=colors, edgecolor="white",
                  linewidth=1.2, label="Latence moyenne")

    # Barre d'erreur min → p95
    yerr_low  = [m - mn for m, mn in zip(lat_mean, lat_min)]
    yerr_high = [p - m for p, m in zip(lat_p95, lat_mean)]
    ax.errorbar(x, lat_mean,
                yerr=[yerr_low, yerr_high],
                fmt="none", color="#1E293B", capsize=6, linewidth=1.5,
                label="Min – P95")

    # Valeurs sur les barres
    for bar, mean, p95 in zip(bars, lat_mean, lat_p95):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                f"{mean:.2f}s\np95: {p95:.2f}s",
                ha="center", va="bottom", fontsize=9, color="#1E293B")

    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=20, ha="right")
    ax.set_ylabel("Latence (secondes)")
    ax.set_title("Axe 1 — Latence des modèles LLM\n"
                 "Barre = moyenne, trait = [min, P95]")
    ax.legend(fontsize=10)
    ax.set_ylim(0, max(lat_p95 or [5]) * 1.4)

    fig.tight_layout()
    fig.savefig(out / "05_latency.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] 05_latency.png")


# ─────────────────────────────────────────────────────────────────────────────
# GRAPHIQUE 6 — Breakdown par catégorie (bad/medium/good)
# ─────────────────────────────────────────────────────────────────────────────

def plot_category_breakdown(raw_results: Dict[str, List], out: Path) -> None:
    """
    Grouped bar chart : taux d'amélioration par catégorie (bad/medium/good)
    pour chaque modèle. Montre si le modèle aide surtout les mauvaises stories.
    """
    categories = ["bad", "medium", "good"]
    models     = list(raw_results.keys())

    # Calcul du taux d'amélioration par catégorie
    data: Dict[str, List[float]] = {cat: [] for cat in categories}
    for model in models:
        stories = raw_results[model]
        for cat in categories:
            cat_stories = [s for s in stories if s.get("category") == cat]
            if cat_stories:
                improved = sum(1 for s in cat_stories if s.get("score_delta", 0) > 0)
                data[cat].append(improved / len(cat_stories) * 100)
            else:
                data[cat].append(0.0)

    x  = np.arange(len(models))
    w  = 0.25
    offsets = [-w, 0, w]

    fig, ax = plt.subplots(figsize=(max(8, len(models) * 2.2), 5.5))

    for i, (cat, offset) in enumerate(zip(categories, offsets)):
        bars = ax.bar(x + offset, data[cat], width=w,
                      color=CAT_COLORS[cat], edgecolor="white",
                      linewidth=1.0, label=cat.capitalize())
        for bar, val in zip(bars, data[cat]):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width() / 2,
                        bar.get_height() + 1,
                        f"{val:.0f}%", ha="center", va="bottom",
                        fontsize=9, color="#1E293B")

    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=20, ha="right")
    ax.set_ylabel("Taux d'amélioration (%)")
    ax.set_ylim(0, 115)
    ax.axhline(100, color="#94A3B8", linestyle="--", linewidth=1)
    ax.set_title("Axe 1 — Taux d'amélioration par catégorie de story\n"
                 "Bad (rouge) · Medium (orange) · Good (vert)")
    ax.legend(fontsize=10)

    fig.tight_layout()
    fig.savefig(out / "06_category_breakdown.png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] 06_category_breakdown.png")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Génère les graphiques du benchmark LLM")
    parser.add_argument("--file", type=Path, default=None,
                        help="Chemin vers le fichier JSON de résultats (défaut: dernier fichier dans results/)")
    args = parser.parse_args()

    print("\n[CHARTS] Generation des graphiques benchmark -- Axe 1 : Performance LLM")
    print("=" * 65)

    data = _load_latest(args.file)
    ranking     = data.get("ranking", [])
    raw_results = data.get("raw_results", {})

    if not ranking:
        print("[ERROR] Aucun resultat dans le fichier.")
        sys.exit(1)

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[OUT] Dossier de sortie : {CHARTS_DIR}\n")
    print(f"   Modeles : {[r['model'] for r in ranking]}")
    print(f"   Stories : {data.get('n_stories', '?')}\n")

    plot_composite_ranking(ranking, CHARTS_DIR)
    plot_radar(ranking, CHARTS_DIR)
    plot_score_progression(raw_results, CHARTS_DIR)
    plot_delta_heatmap(raw_results, CHARTS_DIR)
    plot_latency(ranking, raw_results, CHARTS_DIR)
    plot_category_breakdown(raw_results, CHARTS_DIR)

    print(f"\n[OK] 6 graphiques generes dans :\n   {CHARTS_DIR}\n")
    print("   01_composite_ranking.png  -- Classement general (score composite)")
    print("   02_radar_chart.png        -- Profil multi-dimensionnel (radar)")
    print("   03_score_progression.png  -- Score initial -> final par story")
    print("   04_delta_heatmap.png      -- Heatmap Dscore (stories x modeles)")
    print("   05_latency.png            -- Latence moyenne + P95")
    print("   06_category_breakdown.png -- Taux d'amelioration bad/medium/good\n")


if __name__ == "__main__":
    main()
