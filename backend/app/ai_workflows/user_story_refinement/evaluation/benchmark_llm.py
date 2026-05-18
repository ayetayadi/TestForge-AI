"""
Benchmark LLM — Axe 1 : Performance des modèles Groq.

Compare 5 modèles Groq sur le dataset de 12 user stories.
Pour chaque modèle, mesure deux sources complémentaires :

  ① Rule-based (evaluators.py — déterministe) :
      - score_delta      = final_score - initial_score
      - improvement_rate = % stories améliorées
      - violation_rate   = % contraintes violées
      - latency, success_rate, parse_error_rate

  ② DeepEval GEval (LLM-as-judge — sémantique) :
      - deepeval_score   = note [0..1] donnée par un juge LLM fixe
        (llama-3.3-70b, température 0) à chaque output produit
      - Le juge est TOUJOURS le même modèle, indépendamment du modèle testé.
        Cela garantit une comparaison équitable entre les 5 modèles.

Les deux sources sont combinées dans un score composite final.

Lancement :
  cd backend
  python -m app.ai_workflows.user_story_refinement.evaluation.benchmark_llm

Ou avec un seul modèle (pour valider avant de tout lancer) :
  python -m app.ai_workflows.user_story_refinement.evaluation.benchmark_llm --model Llama-3.3-70B

Sans DeepEval (plus rapide, rule-based seulement) :
  python -m app.ai_workflows.user_story_refinement.evaluation.benchmark_llm --no-deepeval

Avec visualisation Confident AI (dashboard DeepEval) :
  python -m app.ai_workflows.user_story_refinement.evaluation.benchmark_llm --confident
  (se connecte à app.confident-ai.com et affiche les résultats sur le dashboard)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv 


# ── Charger .env AVANT tout import de l'app ───────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[4]   # .../backend
sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(_BACKEND_DIR / ".env")

# ── Imports app ───────────────────────────────────────────────────────────────
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from app.ai_workflows.user_story_refinement.prompts import IMPROVEMENT_PROMPT
from app.ai_workflows.user_story_refinement.evaluators import (
    score_story,
    validate_constraints,
    extract_acceptance_criteria,
)
from app.ai_workflows.user_story_refinement.config import (
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    MIN_SCORE_THRESHOLD,
)
from app.ai_workflows.user_story_refinement.evaluation.dataset import DATASET
from app.ai_workflows.user_story_refinement.evaluation.metrics import (
    compute_model_metrics,
    compare_models,
    format_report,
)

# ── DeepEval ──────────────────────────────────────────────────────────────────
# Import conditionnel : si deepeval n'est pas installé ou si --no-deepeval,
# on désactive silencieusement sans planter le benchmark.
try:
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams
    from deepeval.models.base_model import DeepEvalBaseLLM
    _DEEPEVAL_AVAILABLE = True
except ImportError:
    _DEEPEVAL_AVAILABLE = False
    logger = logging.getLogger("benchmark_llm")
    logging.getLogger("benchmark_llm").warning(
        "DeepEval non installé — benchmark rule-based uniquement. "
        "Installe avec : pip install deepeval"
    )

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("benchmark_llm")

# Réduire le bruit de DeepEval dans les logs
logging.getLogger("deepeval").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION DES MODÈLES À BENCHMARKER
# ─────────────────────────────────────────────────────────────────────────────
# Clé = nom affiché dans le rapport
# Valeur = model ID exact renvoyé par l'API Groq (/v1/models)

MODELS: Dict[str, str] = {
    "Llama-3.3-70B":   "llama-3.3-70b-versatile",
    "Qwen3-32B":       "qwen/qwen3-32b",
    "Llama-3.1-8B":    "llama-3.1-8b-instant",
    "GPT-OSS-120B":    "openai/gpt-oss-120b",
    "GPT-OSS-20B":     "openai/gpt-oss-20b",
}

# Délai entre chaque appel LLM (secondes) — respecte le rate limit Groq
DELAY_BETWEEN_CALLS: float = float(os.getenv("BENCHMARK_DELAY", "3.0"))

# Timeout par appel LLM (secondes)
CALL_TIMEOUT: float = 60.0


# ─────────────────────────────────────────────────────────────────────────────
# MODÈLE JUGE DEEPEVAL (fixe — indépendant du modèle testé)
# ─────────────────────────────────────────────────────────────────────────────
# Le juge est TOUJOURS llama-3.3-70b à température 0 (déterministe).
# Il évalue l'output de chaque modèle testé avec le critère GEval INVEST.
# Utiliser le même juge pour tous les modèles garantit une comparaison équitable.

_JUDGE_MODEL_ID  = "llama-3.3-70b-versatile"
_JUDGE_TEMP      = 0.0
_JUDGE_MAX_TOKENS = 512

_geval_metric = None   # singleton — créé à la première utilisation


def _get_geval_metric(api_key: str):
    """
    Retourne le singleton GEval. Le crée à la première utilisation.
    Utilise un DeepEvalBaseLLM custom qui pointe sur ChatGroq.
    """
    global _geval_metric
    if _geval_metric is not None or not _DEEPEVAL_AVAILABLE:
        return _geval_metric

    class _GroqJudge(DeepEvalBaseLLM):
        def __init__(self):
            self._chat = ChatGroq(
                groq_api_key=api_key,
                model=_JUDGE_MODEL_ID,
                temperature=_JUDGE_TEMP,
                max_tokens=_JUDGE_MAX_TOKENS,
            )
    
        def load_model(self):
            return self._chat
    
        def generate(self, prompt: str, schema=None) -> str:
            """Retourne UNIQUEMENT le contenu texte, pas un tuple."""
            response = self._chat.invoke(prompt)
            return response.content
    
        async def a_generate(self, prompt: str, schema=None) -> str:
            """Retourne UNIQUEMENT le contenu texte, pas un tuple."""
            response = await self._chat.ainvoke(prompt)
            return response.content
    
        def get_model_name(self) -> str:
            return f"groq/{_JUDGE_MODEL_ID}"

    _geval_metric = GEval(
        name="invest_quality",
        # Critère transmis au juge LLM — il note de 0 à 1
        criteria=(
            "Evaluate whether ACTUAL_OUTPUT (the improved user story) is genuinely "
            "better than INPUT (the original user story) according to the INVEST framework. "
            "Award a HIGH score (close to 1.0) when ALL of the following are true:\n"
            "  (1) Format respected: 'As a [role], I want [feature], so that [benefit]'\n"
            "  (2) Vague terms (quickly, easily, seamless, better, fast) are replaced "
            "with measurable conditions\n"
            "  (3) At least 2 acceptance criteria with action verbs AND measurable "
            "outcomes (e.g. 'within 2s', 'minimum 6 characters', 'at least 3 items')\n"
            "  (4) INVEST respected: Independent (no dependency on other stories), "
            "Negotiable (no technology imposed), Valuable (clear business benefit), "
            "Estimable (specific enough), Small (one sprint), Testable\n"
            "  (5) Original actor/role and business intent preserved — no new features invented\n"
            "Award a LOW score (close to 0.0) when the output is identical to the input, "
            "still vague, or violates the original intent."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=_GroqJudge(),
        threshold=0.5,
        async_mode=False,
    )
    return _geval_metric


async def _run_deepeval(
    original_story: str,
    improved_story: str,
    api_key: str,
    confident_mode: bool = False,
) -> Optional[float]:
    """
    Lance GEval en thread (synchrone dans DeepEval) et retourne le score [0..1].

    Avec confident_mode=True : utilise deepeval.evaluate() qui push automatiquement
    les résultats vers app.confident-ai.com (nécessite deepeval.login() au préalable).

    Retourne None si DeepEval n'est pas disponible ou si l'évaluation échoue.
    """
    if not _DEEPEVAL_AVAILABLE:
        return None
    metric = _get_geval_metric(api_key)
    if metric is None:
        return None
    try:
        test_case = LLMTestCase(input=original_story, actual_output=improved_story)
        if confident_mode:
            from deepeval import evaluate
            eval_result = await asyncio.to_thread(
                evaluate, [test_case], [metric]
            )
            try:
                return round(float(eval_result.test_results[0].metrics_data[0].score), 3)
            except (IndexError, AttributeError, TypeError):
                return round(float(metric.score), 3) if metric.score is not None else None
        else:
            await asyncio.to_thread(metric.measure, test_case)
            return round(float(metric.score), 3)
    except Exception as exc:
        logger.warning("[DEEPEVAL] GEval échoué : %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SCHÉMA DE SORTIE DU LLM (identique au pipeline)
# ─────────────────────────────────────────────────────────────────────────────

class ImprovementResult(BaseModel):
    improved_story: str = Field(description="The improved user story text")
    acceptance_criteria: List[str] = Field(description="Improved acceptance criteria list")
    reasoning: str = Field(description="What issues were found and what was changed")


# ─────────────────────────────────────────────────────────────────────────────
# APPEL LLM DIRECT (sans ControlledChatGroq pour éviter les semaphores)
# ─────────────────────────────────────────────────────────────────────────────

def _build_llm(model_id: str, api_key: str) -> Any:
    """Crée un ChatGroq brut (sans rate limiter) avec structured output."""
    llm = ChatGroq(
        groq_api_key=api_key,
        model=model_id,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
    )
    return llm.with_structured_output(ImprovementResult)


def _build_prompt(story: str, ac: List[str], score_result: Dict[str, Any]) -> str:
    return IMPROVEMENT_PROMPT.format(
        story=story,
        acceptance_criteria="\n".join(f"- {a}" for a in ac) if ac else "(none)",
        ac_count=len(ac),
        issues="\n".join(f"- {i}" for i in score_result.get("issues", [])) or "(none)",
        suggestions="\n".join(f"- {s}" for s in score_result.get("suggestions", [])) or "(none)",
        threshold=MIN_SCORE_THRESHOLD,
    )


async def _call_with_retry(
    llm: Any,
    story: str,
    ac: List[str],
    score_result: Dict[str, Any],
) -> tuple[Optional[ImprovementResult], bool, bool]:
    """
    Appelle le LLM et gère les erreurs JSON (même logique que le pipeline).

    Retourne : (result, parse_error, retried)
      result      — ImprovementResult ou None si échec total
      parse_error — True si le JSON était malformé (mais récupéré au 2e essai)
      retried     — True si un 2e essai a été nécessaire
    """
    prompt = _build_prompt(story, ac, score_result)
    try:
        result = await asyncio.wait_for(llm.ainvoke(prompt), timeout=CALL_TIMEOUT)
        return result, False, False
    except Exception as e:
        err_str = str(e)
        # Groq retourne 400 quand max_tokens coupe le JSON en plein milieu
        if any(k in err_str for k in ("tool_use_failed", "Failed to parse", "json", "JSON")):
            short_prompt = prompt + "\n\nIMPORTANT: Keep the reasoning field under 60 words."
            try:
                result = await asyncio.wait_for(llm.ainvoke(short_prompt), timeout=CALL_TIMEOUT)
                return result, True, True   # récupéré au 2e essai
            except Exception:
                return None, True, True     # toujours échoué
        return None, False, False           # erreur non-JSON (timeout, network…)


# ─────────────────────────────────────────────────────────────────────────────
# RUN D'UNE STORY
# ─────────────────────────────────────────────────────────────────────────────

async def run_story(
    llm: Any,
    story_entry: Dict[str, Any],
    story_index: int,
    total_stories: int,
    api_key: str,
    use_deepeval: bool = True,
    confident_mode: bool = False,
) -> Dict[str, Any]:
    """
    Exécute une story à travers :
      1. extract_acceptance_criteria  (no LLM)
      2. score_story initial          (no LLM — rule-based)
      3. LLM call (avec retry JSON)   — modèle testé
      4. validate_constraints         (no LLM — rule-based)
      5. score_story final            (no LLM — rule-based)  ← Métrique ①
      6. DeepEval GEval               (LLM juge fixe)        ← Métrique ②

    Retourne un dict de résultats pour compute_model_metrics().
    """
    story_id = story_entry["id"]
    story    = story_entry["story"]
    raw_ac   = story_entry["acceptance_criteria"]
    category = story_entry["category"]

    print(f"    [{story_index}/{total_stories}] {story_id} ({category}) ...", end=" ", flush=True)

    # ── Étape 1 : extraire et nettoyer les AC ─────────────────────────────────
    extracted = await extract_acceptance_criteria(story, raw_ac)
    ac = extracted.get("acceptance_criteria") or raw_ac

    # ── Étape 2 : score initial ───────────────────────────────────────────────
    initial = await score_story(story, ac)
    initial_score = initial.get("final_score", 0.0)

    # ── Étape 3 : appel LLM ───────────────────────────────────────────────────
    t0 = time.monotonic()
    llm_result, parse_error, retried = await _call_with_retry(llm, story, ac, initial)
    latency_s = round(time.monotonic() - t0, 2)

    if llm_result is None:
        print(f"ÉCHEC (latence={latency_s}s)")
        return {
            "story_id":      story_id,
            "category":      category,
            "language":      story_entry["language"],
            "success":       False,
            "parse_error":   parse_error,
            "retried":       retried,
            "latency_s":     latency_s,
            "initial_score": initial_score,
            "final_score":   initial_score,
            "score_delta":   0.0,
            "violations":    [],
            "deepeval_score": None,
            "error":         "LLM call failed",
        }

    improved_story = llm_result.improved_story or story
    improved_ac    = llm_result.acceptance_criteria or ac

    # ── Étape 4 : valider les contraintes (rule-based) ────────────────────────
    validation = await validate_constraints(story, improved_story, improved_ac)
    violations = validation.get("violations", [])

    # ── Étape 5 : score final rule-based ── Métrique ① ───────────────────────
    final = await score_story(improved_story, improved_ac)
    final_score = final.get("final_score", 0.0)
    score_delta = round(final_score - initial_score, 3)

    # ── Étape 6 : DeepEval GEval (LLM-as-judge) ── Métrique ② ────────────────
    # Le juge (llama-3.3-70b, T=0) lit l'original et l'amélioré et donne un score.
    # On ne l'appelle que si la story a été modifiée (inutile si identical).
    deepeval_score: Optional[float] = None
    if use_deepeval and improved_story != story:
        print(f"[deepeval…] ", end="", flush=True)
        deepeval_score = await _run_deepeval(story, improved_story, api_key, confident_mode=confident_mode)

    status_label = "✓" if score_delta > 0 else ("⚠" if violations else "→")
    geval_str = f" geval={deepeval_score:.3f}" if deepeval_score is not None else ""
    print(
        f"{status_label} Δrule={score_delta:+.3f} "
        f"({initial_score:.3f}→{final_score:.3f})"
        f"{geval_str} "
        f"lat={latency_s}s"
        + (f" [RETRY]" if retried else "")
        + (f" [VIOLATION]" if violations else "")
    )

    return {
        "story_id":       story_id,
        "category":       category,
        "language":       story_entry["language"],
        "success":        True,
        "parse_error":    parse_error,
        "retried":        retried,
        "latency_s":      latency_s,
        "initial_score":  round(initial_score, 3),
        "final_score":    round(final_score, 3),
        "score_delta":    score_delta,
        "violations":     violations,
        "deepeval_score": deepeval_score,   # ② LLM-as-judge [0..1] ou None
        "improved_story": improved_story,
        "reasoning":      llm_result.reasoning,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RUN D'UN MODÈLE COMPLET
# ─────────────────────────────────────────────────────────────────────────────

async def benchmark_model(
    model_name: str,
    model_id: str,
    api_key: str,
    stories: List[Dict[str, Any]],
    use_deepeval: bool = True,
    confident_mode: bool = False,
) -> Dict[str, Any]:
    """
    Benchmark un modèle sur l'ensemble du dataset.
    Ajoute un délai DELAY_BETWEEN_CALLS entre chaque appel pour éviter le rate limit.
    """
    print(f"\n  {'─'*60}")
    print(f"  Modèle : {model_name} ({model_id})")
    print(f"  {'─'*60}")

    llm = _build_llm(model_id, api_key)
    results = []

    for i, entry in enumerate(stories, 1):
        result = await run_story(llm, entry, i, len(stories), api_key, use_deepeval, confident_mode)
        results.append(result)
        if i < len(stories):
            await asyncio.sleep(DELAY_BETWEEN_CALLS)

    metrics = compute_model_metrics(results)
    print(
        f"\n  → success={metrics['success_rate_%']}%  "
        f"amélioration={metrics['improvement_rate_%']}%  "
        f"Δscore={metrics['score_delta_mean']:+.3f}  "
        f"lat={metrics['latency_mean_s']}s"
    )
    return {"metrics": metrics, "raw_results": results}


# ─────────────────────────────────────────────────────────────────────────────
# POINT D'ENTRÉE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

async def main(
    model_filter: Optional[str] = None,
    use_deepeval: bool = True,
    confident_mode: bool = False,
) -> None:
    api_key = os.getenv("GROQ_API_KEY_1", "")
    if not api_key:
        print("ERREUR : GROQ_API_KEY_1 introuvable dans .env")
        sys.exit(1)

    models_to_run = {
        name: mid for name, mid in MODELS.items()
        if model_filter is None or name.lower() == model_filter.lower() or mid == model_filter
    }
    if not models_to_run:
        print(f"ERREUR : modèle '{model_filter}' introuvable. Disponibles : {list(MODELS.keys())}")
        sys.exit(1)

    if use_deepeval and not _DEEPEVAL_AVAILABLE:
        print("  [!] DeepEval non disponible — benchmark rule-based uniquement.")
        use_deepeval = False
        confident_mode = False

    if confident_mode:
        if not use_deepeval:
            print("  [!] --confident ignoré car DeepEval est désactivé.")
            confident_mode = False
        else:
            import deepeval as _deepeval
            confident_key = os.getenv("CONFIDENT_API_KEY", "")
            if not confident_key:
                print("  [!] CONFIDENT_API_KEY non trouvée dans .env")
                print("  [!] --confident désactivé")
                confident_mode = False
            else:
                print("\n  [CONFIDENT AI] Connexion au dashboard DeepEval...")
                _deepeval.login(api_key=confident_key)
                print("  [CONFIDENT AI] Connecté — les résultats seront visibles sur app.confident-ai.com\n")

    stories = DATASET

    print("\n" + "=" * 70)
    print("  BENCHMARK LLM — AXE 1 : PERFORMANCE DES MODÈLES GROQ")
    print("=" * 70)
    print(f"  Modèles testés   : {len(models_to_run)}")
    print(f"  Stories testées  : {len(stories)}")
    print(f"  Délai entre appels : {DELAY_BETWEEN_CALLS}s")
    print(f"  Temperature : {LLM_TEMPERATURE}  |  Max tokens : {LLM_MAX_TOKENS}")
    print(f"  DeepEval GEval   : {'✓ activé (juge = ' + _JUDGE_MODEL_ID + ')' if use_deepeval else '✗ désactivé (--no-deepeval)'}")
    if confident_mode:
        print(f"  Confident AI     : ✓ activé — résultats pushés sur app.confident-ai.com")
    print("=" * 70)

    all_model_metrics: Dict[str, Dict[str, Any]] = {}
    all_raw_results:   Dict[str, List[Dict[str, Any]]] = {}

    t_start = time.monotonic()

    for model_name, model_id in models_to_run.items():
        try:
            data = await benchmark_model(model_name, model_id, api_key, stories, use_deepeval, confident_mode)
            all_model_metrics[model_name] = data["metrics"]
            all_raw_results[model_name]   = data["raw_results"]
        except Exception as exc:
            print(f"\n  ERREUR modèle {model_name}: {exc}")
            all_model_metrics[model_name] = {"error": str(exc)}
            all_raw_results[model_name]   = []

        # Pause entre modèles pour laisser le rate limit se réinitialiser
        if list(models_to_run.keys()).index(model_name) < len(models_to_run) - 1:
            print(f"\n  (pause de 5s avant le prochain modèle...)")
            await asyncio.sleep(5.0)

    t_total = round(time.monotonic() - t_start, 1)

    # ── Rapport final ─────────────────────────────────────────────────────────
    ranking = compare_models(all_model_metrics)
    print(format_report(ranking))
    print(f"  Durée totale du benchmark : {t_total}s\n")

    # ── Sauvegarde JSON ───────────────────────────────────────────────────────
    output_dir = Path(__file__).parent / "results"
    output_dir.mkdir(exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"benchmark_llm_{timestamp}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp":    timestamp,
                "models_tested": list(models_to_run.keys()),
                "n_stories":    len(stories),
                "ranking":      ranking,
                "raw_results":  all_raw_results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"  Résultats sauvegardés dans : {output_path}\n")

    # ── Afficher le modèle recommandé ─────────────────────────────────────────
    if ranking:
        best = ranking[0]
        print(f"  MODÈLE RECOMMANDÉ : {best['model']}")
        print(f"  Score composite   : {best['composite']}")
        print(f"  Score delta moyen : {best.get('score_delta_mean', 0):+.3f}")
        print(f"  Latence moyenne   : {best.get('latency_mean_s', 0)}s\n")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark LLM — Axe 1")
    parser.add_argument(
        "--model",
        default=None,
        help="Tester un seul modèle (nom ou model_id). Omis = tous les modèles.",
    )
    parser.add_argument(
        "--no-deepeval",
        action="store_true",
        help="Désactive DeepEval GEval (benchmark rule-based uniquement, plus rapide).",
    )
    parser.add_argument(
        "--confident",
        action="store_true",
        help="Push les résultats DeepEval vers app.confident-ai.com (dashboard visuel).",
    )
    args = parser.parse_args()
    asyncio.run(main(
        model_filter=args.model,
        use_deepeval=not args.no_deepeval,
        confident_mode=args.confident,
    ))
