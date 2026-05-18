"""
Formules de métriques — Axe 1 : Performance LLM.

Toutes les fonctions prennent une liste de résultats de story (dict)
et retournent un dict de métriques calculées.

Deux sources de métriques complémentaires :
  ① Rule-based (evaluators.py) — déterministe, mesure le FORMAT
  ② DeepEval GEval (LLM-as-judge) — sémantique, mesure la QUALITÉ RÉELLE

Formules :
  success_rate        = calls_success / calls_total × 100
  error_rate          = calls_failed / calls_total × 100
  parse_error_rate    = parse_errors / calls_total × 100
  improvement_rate    = stories_improved / stories_successful × 100
  violation_rate      = stories_with_violations / stories_successful × 100
  latency_mean        = mean(latency_s pour les appels réussis)
  latency_p95         = percentile_95(latency_s pour les appels réussis)
  score_delta_mean    = mean(final_score - initial_score) — rule-based
  deepeval_score_mean = mean(deepeval_score) — LLM-as-judge GEval [0..1]
  second_pass_rate    = stories_with_retry / stories_successful × 100
"""

import math
from typing import Any, Dict, List


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = math.ceil(p / 100 * len(sorted_vals)) - 1
    return sorted_vals[max(0, idx)]


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ─── MÉTRIQUES AXE 1 ──────────────────────────────────────────────────────────

def compute_model_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calcule toutes les métriques Axe 1 pour un modèle donné.

    Paramètre results : liste de dicts retournés par benchmark_llm.run_story().
    Chaque dict contient :
        success       : bool
        parse_error   : bool (JSON malformé mais pas timeout)
        latency_s     : float
        initial_score : float
        final_score   : float
        violations    : list[str]
        retried       : bool (second essai avec prompt raccourci)

    Retourne un dict avec toutes les métriques calculées + formules.
    """
    total = len(results)
    if total == 0:
        return {"error": "no results"}

    successful = [r for r in results if r.get("success")]
    failed     = [r for r in results if not r.get("success")]
    parse_err  = [r for r in results if r.get("parse_error")]
    improved   = [r for r in successful if r.get("score_delta", 0) > 0]
    violated   = [r for r in successful if r.get("violations")]
    retried    = [r for r in successful if r.get("retried")]

    latencies       = [r["latency_s"]      for r in successful if "latency_s"      in r]
    score_deltas    = [r["score_delta"]    for r in successful if "score_delta"    in r]
    final_scores    = [r["final_score"]    for r in successful if "final_score"    in r]
    deepeval_scores = [r["deepeval_score"] for r in successful if r.get("deepeval_score") is not None]

    n_ok = len(successful)

    # ── Formules ──────────────────────────────────────────────────────────────
    # ① Rule-based (evaluators.py — regex/formules Python)
    #   success_rate     = |successful| / total × 100
    #   error_rate       = |failed| / total × 100
    #   parse_error_rate = |parse_err| / total × 100
    #   improvement_rate = |improved| / |successful| × 100
    #   violation_rate   = |violated| / |successful| × 100
    #   second_pass_rate = |retried| / |successful| × 100
    #   latency_mean     = Σ latency_s / |successful|
    #   latency_p95      = percentile(latency_s, 95)
    #   score_delta_mean = Σ(final_score - initial_score) / |successful|
    #
    # ② DeepEval GEval (LLM-as-judge — modèle juge fixe : llama-3.3-70b)
    #   deepeval_score_mean = Σ(geval_score) / |successful avec score|
    #   → score [0..1] : 1.0 = story parfaitement améliorée selon le juge LLM
    # ──────────────────────────────────────────────────────────────────────────

    return {
        # Fiabilité
        "success_rate_%":       round(len(successful) / total * 100, 1),
        "error_rate_%":         round(len(failed) / total * 100, 1),
        "parse_error_rate_%":   round(len(parse_err) / total * 100, 1),

        # Latence (secondes)
        "latency_mean_s":       round(_mean(latencies), 2),
        "latency_p95_s":        round(_percentile(latencies, 95), 2),
        "latency_min_s":        round(min(latencies, default=0), 2),
        "latency_max_s":        round(max(latencies, default=0), 2),

        # ① Qualité rule-based (evaluators.py)
        "improvement_rate_%":   round(len(improved) / max(n_ok, 1) * 100, 1),
        "violation_rate_%":     round(len(violated) / max(n_ok, 1) * 100, 1),
        "score_delta_mean":     round(_mean(score_deltas), 3),
        "final_score_mean":     round(_mean(final_scores), 3),

        # ② Qualité sémantique (DeepEval GEval — LLM-as-judge)
        "deepeval_score_mean":  round(_mean(deepeval_scores), 3) if deepeval_scores else None,
        "deepeval_n_evaluated": len(deepeval_scores),

        # Comportement
        "second_pass_rate_%":   round(len(retried) / max(n_ok, 1) * 100, 1),

        # Comptages bruts
        "n_total":    total,
        "n_success":  n_ok,
        "n_failed":   len(failed),
        "n_parse_err": len(parse_err),
        "n_improved": len(improved),
        "n_violated": len(violated),
        "n_retried":  len(retried),
    }


def compare_models(model_metrics: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Construit un classement des modèles basé sur un score composite.

    Score composite (0–100) combinant les deux sources de qualité :

        composite = (
            deepeval_score_mean × 40   # ② LLM-as-judge (qualité sémantique)
          + score_delta_mean    × 25   # ① Rule-based (amélioration de format)
          + improvement_rate    × 0.15 # fréquence d'amélioration
          + success_rate        × 0.10 # fiabilité
          - violation_rate      × 0.05 # pénalité violations
          - latency_mean        × 1    # pénalité latence (par seconde)
          - parse_error_rate    × 0.05 # pénalité erreurs JSON
        )

    Si DeepEval n'a pas pu tourner (deepeval_score_mean=None),
    le score composite se base uniquement sur les métriques rule-based.
    """
    ranking = []
    for model_name, m in model_metrics.items():
        if "error" in m:
            composite = 0.0
        else:
            deepeval = m.get("deepeval_score_mean")
            if deepeval is not None:
                # Avec DeepEval : les deux sources combinées
                composite = (
                    deepeval                         * 40
                    + m.get("score_delta_mean", 0)   * 25
                    + m.get("improvement_rate_%", 0) * 0.15
                    + m.get("success_rate_%", 0)     * 0.10
                    - m.get("violation_rate_%", 0)   * 0.05
                    - m.get("latency_mean_s", 0)     * 1
                    - m.get("parse_error_rate_%", 0) * 0.05
                )
            else:
                # Sans DeepEval : rule-based uniquement
                composite = (
                    m.get("score_delta_mean", 0)     * 35
                    + m.get("improvement_rate_%", 0) * 0.25
                    + m.get("success_rate_%", 0)     * 0.20
                    - m.get("violation_rate_%", 0)   * 0.10
                    - m.get("latency_mean_s", 0)     * 2
                    - m.get("parse_error_rate_%", 0) * 0.10
                )
        ranking.append({
            "model":     model_name,
            "composite": round(composite, 2),
            **m,
        })

    ranking.sort(key=lambda x: x["composite"], reverse=True)
    for i, row in enumerate(ranking):
        row["rank"] = i + 1
    return ranking


def format_report(ranking: List[Dict[str, Any]]) -> str:
    """Affiche un tableau comparatif lisible dans le terminal."""
    sep = "─" * 120
    lines = [
        "",
        "=" * 120,
        "  AXE 1 — PERFORMANCE LLM : RÉSULTATS DU BENCHMARK",
        "  Sources : ① Rule-based (evaluators.py)  |  ② DeepEval GEval (LLM-as-judge, juge fixe : llama-3.3-70b)",
        "=" * 120,
        f"{'#':<3} {'Modèle':<24} {'Score↑':>7} "
        f"{'GEval②':>7} {'Δrule①':>7} "
        f"{'Amélioré':>9} {'Succès':>7} {'Violation':>10} "
        f"{'Lat.moy':>8} {'Lat.p95':>8} {'ParseErr':>9}",
        sep,
    ]

    for r in ranking:
        deepeval = r.get("deepeval_score_mean")
        deepeval_str = f"{deepeval:.3f}" if deepeval is not None else "  N/A "
        lines.append(
            f"{r['rank']:<3} {r['model']:<24} "
            f"{r.get('composite', 0):>7.1f} "
            f"{deepeval_str:>7} "
            f"{r.get('score_delta_mean', 0):>+7.3f} "
            f"{r.get('improvement_rate_%', 0):>8.1f}% "
            f"{r.get('success_rate_%', 0):>6.1f}% "
            f"{r.get('violation_rate_%', 0):>9.1f}% "
            f"{r.get('latency_mean_s', 0):>7.2f}s "
            f"{r.get('latency_p95_s', 0):>7.2f}s "
            f"{r.get('parse_error_rate_%', 0):>8.1f}% "
        )

    lines += [sep, ""]
    lines.append("  GEval② = DeepEval LLM-as-judge [0..1] — qualité sémantique (mesurée par un juge LLM externe)")
    lines.append("  Δrule① = score_delta rule-based — amélioration de format (evaluators.py)")
    lines.append("  Score composite = GEval×40 + Δrule×25 + amélioration×0.15 + succès×0.10 - violation×0.05 - latence×1")
    lines.append("  → Plus le score est élevé, meilleur est le modèle pour cette tâche.\n")
    return "\n".join(lines)
