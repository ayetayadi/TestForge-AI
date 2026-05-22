"""
Benchmark LLM — Axe 1 : Performance des modèles Groq.

Compare 3 modèles Groq sur le dataset de 8 user stories.
Pour chaque modèle, mesure deux sources complémentaires :

  ① Rule-based (evaluators.py — déterministe) :
      - score_delta      = final_score - initial_score
      - improvement_rate = % stories améliorées
      - violation_rate   = % contraintes violées
      - latency, success_rate, parse_error_rate

  ② Root Signals Judge (LLM-as-judge — sémantique) :
      - deepeval_score   = note [0..1] donnée par RootSignals-Judge-Llama-70B
      - Le juge est TOUJOURS le même modèle, indépendamment du modèle testé.
        Cela garantit une comparaison équitable entre les 3 modèles.

Les deux sources sont combinées dans un score composite final.

Lancement (tous les modèles) :
  cd backend
  python -m app.ai_workflows.user_story_refinement.evaluation.benchmark_llm

Avec un seul modèle (test rapide ~5 min) :
  python -m app.ai_workflows.user_story_refinement.evaluation.benchmark_llm --model Llama-3.3-70B

Sans Root Signals (rule-based seulement, ~2 min par modèle) :
  python -m app.ai_workflows.user_story_refinement.evaluation.benchmark_llm --no-rootsignals

Comparaison finale après plusieurs runs séparés (--model) :
  python -m app.ai_workflows.user_story_refinement.evaluation.benchmark_llm --compare-results
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

# ── Root Signals Judge ────────────────────────────────────────────────────────
# Juge externe spécialisé pour l'évaluation LLM-as-a-judge.
# Complètement indépendant des modèles testés → zéro biais d'auto-évaluation.
try:
    from root import RootSignals as _RootSignals
    _ROOT_AVAILABLE = True
except ImportError:
    _ROOT_AVAILABLE = False

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("benchmark_llm")
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
# ROOT SIGNALS JUDGE (juge externe, neutre, spécialisé pour l'évaluation LLM)
# ─────────────────────────────────────────────────────────────────────────────
# Root Signals utilise leur modèle juge par défaut (calibré pour l'évaluation LLM).
# Distinct des modèles testés → zéro biais d'auto-évaluation.
# Le même juge est utilisé pour TOUS les modèles testés → équité garantie.

_root_evaluator = None   # singleton — créé à la première utilisation

_INVEST_PREDICATE = (
    "CONTEXT — PURPOSE OF THIS EVALUATION:\n"
    "These user stories will be used to automatically generate software test cases. "
    "The ONLY goal of the improvement is to REMOVE AMBIGUITY so that tests can be written "
    "without interpretation. The business context, the actor, and the original feature "
    "MUST be preserved exactly — the LLM must clarify, not rewrite.\n\n"
    "Original story (given to the LLM to clarify): {{request}}\n\n"
    "Improved story (produced by the LLM under test): {{response}}\n\n"
    "Score HIGH (close to 1.0) when ALL of the following are true:\n"
    "  (1) Ambiguity removed: vague terms (quickly, easily, seamless, better, fast) "
    "replaced with concrete, measurable conditions (e.g. 'within 2s', 'at least 8 characters', "
    "'maximum 3 attempts') — a tester can write a test case without guessing\n"
    "  (2) Format respected: 'As a [role], I want [feature], so that [benefit]'\n"
    "  (3) At least 2 acceptance criteria, each with an action verb AND a measurable outcome\n"
    "  (4) INVEST respected: Independent, Negotiable (no technology imposed), "
    "Valuable, Estimable, Small, Testable\n"
    "  (5) CONTEXT PRESERVED: same actor/role, same feature, same business goal — "
    "no new features invented, no scope changed, no intent altered\n\n"
    "Score LOW (close to 0.0) when:\n"
    "  - the improved story is identical or still vague (ambiguity not removed)\n"
    "  - the actor, feature, or business goal was changed\n"
    "  - new unrelated features were added\n"
    "  - a tester still cannot write a test case without interpreting the story"
)


_EVALUATOR_NAME = "INVEST Quality Judge — TestForge"


def _get_root_evaluator(root_api_key: str):
    """
    Retourne le singleton Root Signals evaluator (objet avec .run()).
    Cherche d'abord par nom — si trouvé, récupère l'objet complet via son ID.
    list() retourne des métadonnées sans .run() ; get(id) retourne l'objet callable.
    """
    global _root_evaluator
    if _root_evaluator is not None:
        return _root_evaluator
    if not _ROOT_AVAILABLE or not root_api_key:
        return None
    try:
        client = _RootSignals(api_key=root_api_key)
        for ev in client.evaluators.list():
            if ev.name == _EVALUATOR_NAME:
                logger.info("[ROOTSIGNALS] Évaluateur existant trouvé : %s", ev.id)
                # list() retourne des métadonnées — get() retourne l'objet callable avec .run()
                try:
                    _root_evaluator = client.evaluators.get(ev.id)
                except Exception:
                    _root_evaluator = client.evaluators.retrieve(ev.id)
                return _root_evaluator
        _root_evaluator = client.evaluators.create(
            name=_EVALUATOR_NAME,
            intent=(
                "Evaluate whether the improved user story is genuinely better "
                "than the original according to the INVEST framework"
            ),
            predicate=_INVEST_PREDICATE,
            model="gpt-4o",
        )
        logger.info("[ROOTSIGNALS] Évaluateur créé : %s", _root_evaluator.id)
        return _root_evaluator
    except Exception as exc:
        logger.warning("[ROOTSIGNALS] Création de l'évaluateur échouée : %s", exc)
        return None


async def _run_rootsignals(
    original_story: str,
    improved_story: str,
    root_api_key: str,
) -> Optional[float]:
    """
    Appelle le Root Signals Judge et retourne le score [0..1].
    Si l'évaluateur mis en cache n'a pas .run() (EvaluatorListOutput),
    recrée un évaluateur callable via create().
    """
    if not _ROOT_AVAILABLE:
        return None
    evaluator = _get_root_evaluator(root_api_key)
    if evaluator is None:
        return None
    try:
        result = await asyncio.to_thread(
            evaluator.run,
            request=original_story,
            response=improved_story,
        )
        return round(float(result.score), 3)
    except AttributeError:
        # L'objet mis en cache n'a pas .run() — on recrée un évaluateur callable
        logger.warning("[ROOTSIGNALS] Objet sans .run() — recréation de l'évaluateur")
        global _root_evaluator
        _root_evaluator = None   # reset du cache
        try:
            client = _RootSignals(api_key=root_api_key)
            _root_evaluator = client.evaluators.create(
                name=_EVALUATOR_NAME + " (run)",
                intent=(
                    "Evaluate whether the improved user story is genuinely better "
                    "than the original according to the INVEST framework"
                ),
                predicate=_INVEST_PREDICATE,
                model="gpt-4o",
            )
            result = await asyncio.to_thread(
                _root_evaluator.run,
                request=original_story,
                response=improved_story,
            )
            return round(float(result.score), 3)
        except Exception as exc2:
            logger.warning("[ROOTSIGNALS] Recréation échouée : %s", exc2)
            return None
    except Exception as exc:
        logger.warning("[ROOTSIGNALS] Évaluation échouée : %s", exc)
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
    groq_api_key: str,
    root_api_key: str,
    use_rootsignals: bool = True,
) -> Dict[str, Any]:
    """
    Exécute une story à travers :
      1. extract_acceptance_criteria  (no LLM)
      2. score_story initial          (no LLM — rule-based)
      3. LLM call (avec retry JSON)   — modèle testé
      4. validate_constraints         (no LLM — rule-based)
      5. score_story final            (no LLM — rule-based)        ← Métrique ①
      6. Root Signals Judge           (juge externe, neutre)       ← Métrique ②

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

    # ── Étape 6 : Root Signals Judge (LLM-as-judge externe) ── Métrique ② ─────
    # RootSignals-Judge-Llama-70B est distinct de tous les modèles testés.
    # On ne l'appelle que si la story a été modifiée (inutile si identique).
    deepeval_score: Optional[float] = None
    if use_rootsignals and improved_story != story:
        print(f"[root…] ", end="", flush=True)
        deepeval_score = await _run_rootsignals(story, improved_story, root_api_key)

    status_label = "✓" if score_delta > 0 else ("⚠" if violations else "→")
    root_str = f" root={deepeval_score:.3f}" if deepeval_score is not None else ""
    print(
        f"{status_label} Δrule={score_delta:+.3f} "
        f"({initial_score:.3f}→{final_score:.3f})"
        f"{root_str} "
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
        "deepeval_score": deepeval_score,   # ② Root Signals Judge [0..1] ou None
        "improved_story": improved_story,
        "reasoning":      llm_result.reasoning,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RUN D'UN MODÈLE COMPLET
# ─────────────────────────────────────────────────────────────────────────────

async def benchmark_model(
    model_name: str,
    model_id: str,
    groq_api_key: str,
    root_api_key: str,
    stories: List[Dict[str, Any]],
    use_rootsignals: bool = True,
) -> Dict[str, Any]:
    """
    Benchmark un modèle sur l'ensemble du dataset.
    Ajoute un délai DELAY_BETWEEN_CALLS entre chaque appel pour éviter le rate limit.
    """
    print(f"\n  {'─'*60}")
    print(f"  Modèle : {model_name} ({model_id})")
    print(f"  {'─'*60}")

    llm = _build_llm(model_id, groq_api_key)
    results = []

    for i, entry in enumerate(stories, 1):
        result = await run_story(
            llm, entry, i, len(stories),
            groq_api_key, root_api_key, use_rootsignals,
        )
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
    use_rootsignals: bool = True,
) -> None:
    groq_api_key = os.getenv("GROQ_API_KEY_1", "")
    if not groq_api_key:
        print("ERREUR : GROQ_API_KEY_1 introuvable dans .env")
        sys.exit(1)

    root_api_key = os.getenv("ROOTSIGNALS_API_KEY", "")
    if use_rootsignals and not root_api_key:
        print("  [!] ROOTSIGNALS_API_KEY introuvable dans .env — Root Signals Judge désactivé.")
        use_rootsignals = False
    if use_rootsignals and not _ROOT_AVAILABLE:
        print("  [!] root-signals non installé — Root Signals Judge désactivé.")
        print("  [!] Installe avec : pip install root-signals")
        use_rootsignals = False

    models_to_run = {
        name: mid for name, mid in MODELS.items()
        if model_filter is None or name.lower() == model_filter.lower() or mid == model_filter
    }
    if not models_to_run:
        print(f"ERREUR : modèle '{model_filter}' introuvable. Disponibles : {list(MODELS.keys())}")
        sys.exit(1)

    stories = DATASET

    print("\n" + "=" * 70)
    print("  BENCHMARK LLM — AXE 1 : PERFORMANCE DES MODÈLES GROQ")
    print("=" * 70)
    print(f"  Modèles testés   : {len(models_to_run)}")
    print(f"  Stories testées  : {len(stories)}")
    print(f"  Délai entre appels : {DELAY_BETWEEN_CALLS}s")
    print(f"  Temperature : {LLM_TEMPERATURE}  |  Max tokens : {LLM_MAX_TOKENS}")
    if use_rootsignals:
        print(f"  Juge sémantique  : ✓ Root Signals Judge (RootSignals-Judge-Llama-70B)")
        print(f"                     Juge externe — distinct de tous les modèles testés")
    else:
        print(f"  Juge sémantique  : ✗ désactivé (--no-rootsignals)")
    print("=" * 70)

    all_model_metrics: Dict[str, Dict[str, Any]] = {}
    all_raw_results:   Dict[str, List[Dict[str, Any]]] = {}

    t_start = time.monotonic()

    for model_name, model_id in models_to_run.items():
        try:
            data = await benchmark_model(
                model_name, model_id, groq_api_key, root_api_key, stories, use_rootsignals,
            )
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
# MERGE ET COMPARAISON DEPUIS LES FICHIERS JSON (--compare-results)
# ─────────────────────────────────────────────────────────────────────────────

def compare_results_from_files() -> None:
    """
    Lit tous les fichiers results/benchmark_llm_*.json, fusionne les raw_results
    par modèle, recalcule les métriques et affiche le classement comparatif.

    Utile quand les modèles ont été lancés séparément avec --model.
    Chaque fichier peut contenir un ou plusieurs modèles.
    Si un modèle apparaît dans plusieurs fichiers, le fichier le plus récent gagne.
    """
    results_dir = Path(__file__).parent / "results"
    json_files = sorted(results_dir.glob("benchmark_llm_*.json"))

    if not json_files:
        print(f"\n  Aucun fichier trouvé dans : {results_dir}")
        print("  Lance d'abord : python -m ... --model <NOM>\n")
        return

    print(f"\n  Lecture de {len(json_files)} fichier(s) dans {results_dir}/")

    merged_raw: Dict[str, List[Dict[str, Any]]] = {}

    for path in json_files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        raw: Dict[str, List] = data.get("raw_results", {})
        for model_name, results in raw.items():
            if results:
                merged_raw[model_name] = results
                print(f"    ✓ {path.name}  →  {model_name} ({len(results)} stories)")

    if not merged_raw:
        print("  Aucun résultat utilisable trouvé.\n")
        return

    all_model_metrics = {
        model_name: compute_model_metrics(results)
        for model_name, results in merged_raw.items()
    }

    ranking = compare_models(all_model_metrics)
    print(format_report(ranking))

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
        "--no-rootsignals",
        action="store_true",
        help="Désactive Root Signals Judge (benchmark rule-based uniquement, plus rapide).",
    )
    parser.add_argument(
        "--compare-results",
        action="store_true",
        help="Fusionne tous les fichiers JSON dans results/ et affiche le classement comparatif.",
    )
    args = parser.parse_args()

    if args.compare_results:
        compare_results_from_files()
    else:
        asyncio.run(main(
            model_filter=args.model,
            use_rootsignals=not args.no_rootsignals,
        ))
