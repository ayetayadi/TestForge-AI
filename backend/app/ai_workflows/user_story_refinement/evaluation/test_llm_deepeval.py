"""
test_llm_deepeval.py — Suite de tests DeepEval pour le pipeline User Story Refinement.

Ce fichier utilise l'API officielle DeepEval (LLMTestCase + evaluate()) pour
produire un rapport HTML interactif utilisable dans le rapport PFE.

3 métriques complémentaires par test case :
  ① GEval INVEST     — qualité sémantique globale (juge LLM, Groq)
  ② AnswerRelevancy  — la sortie répond-elle à la demande d'amélioration ?
  ③ Faithfulness     — la sortie reste-elle fidèle à l'intent original ?

Chaque LLMTestCase représente une story du dataset :
  input          = story originale (ce qu'on demande d'améliorer)
  actual_output  = story améliorée par le LLM testé
  expected_output = description de ce qu'on attendait (pour Faithfulness)
  retrieval_context = critères INVEST + issues détectées (contexte du juge)

Modes de lancement :
  # Mode pytest (rapport terminal + DeepEval cloud optionnel)
  cd backend
  python -m pytest app/ai_workflows/user_story_refinement/evaluation/test_llm_deepeval.py -v

  # Mode standalone (génère results/deepeval_report.json + affiche le résumé)
  python -m app.ai_workflows.user_story_refinement.evaluation.test_llm_deepeval

  # Sur un modèle spécifique depuis les résultats existants :
  python -m app.ai_workflows.user_story_refinement.evaluation.test_llm_deepeval --model Llama-3.3-70B

  # Lancer le pipeline d'abord puis évaluer (end-to-end) :
  python -m app.ai_workflows.user_story_refinement.evaluation.test_llm_deepeval --run-pipeline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Charger .env AVANT tout import de l'app ───────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(_BACKEND_DIR / ".env")

# ── Imports app ───────────────────────────────────────────────────────────────
from langchain_groq import ChatGroq
from pydantic import BaseModel, Field

from app.ai_workflows.user_story_refinement.evaluators import (
    score_story,
    extract_acceptance_criteria,
)
from app.ai_workflows.user_story_refinement.config import (
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    MIN_SCORE_THRESHOLD,
)
from app.ai_workflows.user_story_refinement.prompts import IMPROVEMENT_PROMPT
from app.ai_workflows.user_story_refinement.evaluation.dataset import DATASET

logging.basicConfig(level=logging.WARNING)
logging.getLogger("deepeval").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logger = logging.getLogger("test_llm_deepeval")

RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

_JUDGE_MODEL_ID   = "llama-3.3-70b-versatile"
_JUDGE_TEMP       = 0.0
_JUDGE_MAX_TOKENS = 1024

# Modèle par défaut pour le pipeline (si --run-pipeline)
_DEFAULT_TEST_MODEL = "llama-3.3-70b-versatile"
_DEFAULT_MODEL_NAME = "Llama-3.3-70B"


# ─────────────────────────────────────────────────────────────────────────────
# DEEPEVAL — IMPORTS ET JUGE GROQ
# ─────────────────────────────────────────────────────────────────────────────

try:
    import deepeval
    from deepeval import assert_test, evaluate
    from deepeval.metrics import GEval, AnswerRelevancyMetric, FaithfulnessMetric
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams
    from deepeval.models.base_model import DeepEvalBaseLLM
    from deepeval.dataset import EvaluationDataset
    _DEEPEVAL_AVAILABLE = True
except ImportError:
    _DEEPEVAL_AVAILABLE = False
    print("[WARN] DeepEval non installe. Installe avec : pip install deepeval")


def _build_groq_judge(api_key: str):
    """
    Crée le modèle juge DeepEval basé sur ChatGroq.
    Toujours llama-3.3-70b à T=0 — indépendant du modèle testé.
    """
    if not _DEEPEVAL_AVAILABLE:
        return None

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

        def generate(self, prompt: str, schema=None):
            response = self._chat.invoke(prompt)
            return response.content

        async def a_generate(self, prompt: str, schema=None):
            response = await self._chat.ainvoke(prompt)
            return response.content

        def get_model_name(self) -> str:
            return f"groq/{_JUDGE_MODEL_ID}"

    return _GroqJudge()


# ─────────────────────────────────────────────────────────────────────────────
# MÉTRIQUES DEEPEVAL
# ─────────────────────────────────────────────────────────────────────────────

_INVEST_CRITERIA = (
    "Evaluate whether ACTUAL_OUTPUT (the improved user story) is genuinely "
    "better than INPUT (the original user story) according to the INVEST framework. "
    "Award a HIGH score (close to 1.0) when ALL of the following are true:\n"
    "  (1) Format respected: 'As a [role], I want [feature], so that [benefit]'\n"
    "  (2) Vague terms replaced with measurable conditions\n"
    "  (3) At least 2 acceptance criteria with action verbs AND measurable outcomes\n"
    "  (4) INVEST respected: Independent, Negotiable (no technology imposed), "
    "Valuable (clear business benefit), Estimable, Small, Testable\n"
    "  (5) Original actor/role and business intent preserved\n"
    "Award a LOW score (close to 0.0) when the output is identical to input, "
    "still vague, or violates the original intent."
)

_RELEVANCY_INSTRUCTIONS = (
    "The input is a user story to improve. "
    "The output should be an improved version respecting the INVEST framework. "
    "Score high if the output directly improves the input story with concrete "
    "acceptance criteria and measurable conditions."
)

_FAITHFULNESS_INSTRUCTIONS = (
    "The retrieval context describes the original user story's role and business goal. "
    "Score high if the improved story preserves the same role, feature, and business benefit. "
    "Score low if the role changed, new unrelated features were added, or intent was distorted."
)


def build_metrics(judge) -> List[Any]:
    """
    Crée les 3 métriques DeepEval.
    Toutes utilisent le même juge Groq fixe (llama-3.3-70b, T=0).
    """
    if not _DEEPEVAL_AVAILABLE or judge is None:
        return []

    return [
        # ① Qualité INVEST globale — LLM-as-judge
        GEval(
            name="INVEST Quality",
            criteria=_INVEST_CRITERIA,
            evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
            model=judge,
            threshold=0.5,
            async_mode=False,
        ),
        # ② Pertinence de la réponse — la sortie répond-elle à la demande ?
        AnswerRelevancyMetric(
            threshold=0.5,
            model=judge,
            async_mode=False,
        ),
        # ③ Fidélité — la sortie reste-elle fidèle à l'intent original ?
        FaithfulnessMetric(
            threshold=0.5,
            model=judge,
            async_mode=False,
        ),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCTION DES TEST CASES
# ─────────────────────────────────────────────────────────────────────────────

def _invest_context(entry: Dict) -> str:
    """Contexte INVEST fourni au juge pour évaluer la fidélité."""
    issues = entry.get("expected_issues", [])
    issues_str = "\n".join(f"  - {i}" for i in issues) if issues else "  (none identified)"
    return (
        f"Original story: {entry['story']}\n"
        f"Category: {entry['category']} | Language: {entry['language']}\n"
        f"Known issues:\n{issues_str}"
    )


def build_test_cases(
    model_name: str,
    raw_stories: List[Dict],
) -> List[LLMTestCase]:
    """
    Construit un LLMTestCase DeepEval pour chaque story du résultat benchmark.

    Champs du LLMTestCase :
      input            = story originale (demande d'amélioration)
      actual_output    = story améliorée par le LLM testé
      expected_output  = description de l'amélioration idéale attendue
      retrieval_context = contexte INVEST pour le juge Faithfulness
      name             = story_id (pour l'identifier dans le rapport)
    """
    test_cases = []
    dataset_map = {e["id"]: e for e in DATASET}

    for s in raw_stories:
        if not s.get("success"):
            continue   # on n'évalue que les succès

        story_id = s["story_id"]
        entry    = dataset_map.get(story_id, {})
        category = s.get("category", "?")

        # Description de l'amélioration idéale (expected_output)
        if category == "bad":
            expected = (
                "A well-formed user story with: clear role, specific feature, "
                "measurable business value ('so that'), and at least 2 acceptance "
                "criteria with action verbs and measurable conditions."
            )
        elif category == "medium":
            expected = (
                "An improved user story keeping the original role and feature, "
                "with strengthened acceptance criteria that include measurable "
                "conditions (quantities, durations, thresholds)."
            )
        else:  # good
            expected = (
                "The story should be preserved or minimally improved — "
                "original AC must not be weakened or removed."
            )

        tc = LLMTestCase(
            input=entry.get("story", s.get("improved_story", "")),
            actual_output=s.get("improved_story", ""),
            expected_output=expected,
            retrieval_context=[_invest_context(entry)] if entry else None,
            name=f"{model_name}::{story_id}",
        )
        test_cases.append(tc)

    return test_cases


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE LLM (si --run-pipeline, pour générer les improved stories)
# ─────────────────────────────────────────────────────────────────────────────

class _ImprovementResult(BaseModel):
    improved_story:     str       = Field(description="The improved user story text")
    acceptance_criteria: List[str] = Field(description="Improved acceptance criteria list")
    reasoning:          str       = Field(description="What was changed and why")


async def _run_pipeline_for_entry(
    llm: Any,
    entry: Dict,
) -> Optional[Dict]:
    """Lance le pipeline d'amélioration sur une story et retourne le résultat brut."""
    try:
        t0  = time.perf_counter()
        ac  = await extract_acceptance_criteria(entry["story"], entry.get("acceptance_criteria", []))
        sr  = await score_story(entry["story"], ac)

        prompt = IMPROVEMENT_PROMPT.format(
            story=entry["story"],
            acceptance_criteria="\n".join(f"- {a}" for a in ac) if ac else "(none)",
            ac_count=len(ac),
            issues="\n".join(f"- {i}" for i in sr.get("issues", [])) or "(none)",
            suggestions="\n".join(f"- {s}" for s in sr.get("suggestions", [])) or "(none)",
            threshold=MIN_SCORE_THRESHOLD,
        )
        result: _ImprovementResult = await llm.ainvoke(prompt)
        latency = round(time.perf_counter() - t0, 3)

        final_sr = await score_story(result.improved_story, result.acceptance_criteria)
        return {
            "story_id":      entry["id"],
            "category":      entry["category"],
            "language":      entry["language"],
            "success":       True,
            "latency_s":     latency,
            "initial_score": round(sr.get("score", 0), 3),
            "final_score":   round(final_sr.get("score", 0), 3),
            "score_delta":   round(final_sr.get("score", 0) - sr.get("score", 0), 3),
            "improved_story": result.improved_story,
            "acceptance_criteria": result.acceptance_criteria,
            "reasoning":     result.reasoning,
        }
    except Exception as exc:
        logger.warning("[PIPELINE] %s failed: %s", entry["id"], exc)
        return {
            "story_id": entry["id"],
            "category": entry["category"],
            "language": entry["language"],
            "success":  False,
            "error":    str(exc),
        }


async def run_pipeline(model_id: str, api_key: str) -> List[Dict]:
    """Lance le pipeline sur toutes les stories du dataset."""
    llm = ChatGroq(
        groq_api_key=api_key,
        model=model_id,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
    ).with_structured_output(_ImprovementResult)

    results = []
    for i, entry in enumerate(DATASET):
        print(f"  [{i+1}/{len(DATASET)}] {entry['id']} ...", end=" ", flush=True)
        r = await _run_pipeline_for_entry(llm, entry)
        status = "OK" if r and r.get("success") else "FAIL"
        print(status)
        results.append(r)
        await asyncio.sleep(2.0)   # respecte le rate limit Groq

    return [r for r in results if r]


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATION DEEPEVAL
# ─────────────────────────────────────────────────────────────────────────────

def run_deepeval_evaluation(
    model_name: str,
    raw_stories: List[Dict],
    api_key: str,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Construit les LLMTestCase et lance deepeval.evaluate().
    Retourne un dict avec les résultats agrégés.
    """
    if not _DEEPEVAL_AVAILABLE:
        print("[WARN] DeepEval non disponible — evaluation ignoree.")
        return {}

    print(f"\n[DEEPEVAL] Construction des test cases pour : {model_name}")
    test_cases = build_test_cases(model_name, raw_stories)
    print(f"  {len(test_cases)} test cases construits ({len(raw_stories)} stories)")

    judge   = _build_groq_judge(api_key)
    metrics = build_metrics(judge)

    if not metrics:
        print("[WARN] Aucune metrique disponible.")
        return {}

    print(f"  Metriques : {[m.__class__.__name__ for m in metrics]}")
    print(f"  Juge      : groq/{_JUDGE_MODEL_ID} (T={_JUDGE_TEMP})\n")

    # Lance l'evaluation DeepEval
    # run_async=False : on est deja dans un contexte synchrone ici
    eval_results = evaluate(
        test_cases=test_cases,
        metrics=metrics,
        run_async=False,
    )

    # Agrege les resultats
    summary = _aggregate_results(eval_results, metrics)
    summary["model"] = model_name
    summary["n_test_cases"] = len(test_cases)

    # Sauvegarde JSON
    out_path = RESULTS_DIR / f"deepeval_{model_name.replace('/', '_')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] Resultats sauvegardes : {out_path}")

    return summary


def _aggregate_results(eval_results: Any, metrics: List[Any]) -> Dict[str, Any]:
    """Extrait les scores moyens et le taux de réussite par métrique."""
    metric_names = [m.__class__.__name__ for m in metrics]
    scores: Dict[str, List[float]] = {n: [] for n in metric_names}
    passed: Dict[str, int]         = {n: 0 for n in metric_names}
    total = 0

    try:
        # eval_results est un EvaluationResult de DeepEval
        for tc_result in eval_results.test_results:
            total += 1
            for m_result in tc_result.metrics_metadata:
                name = m_result.metric
                if name in scores:
                    if m_result.score is not None:
                        scores[name].append(float(m_result.score))
                    if m_result.success:
                        passed[name] += 1
    except Exception as exc:
        logger.warning("[AGGREGATE] Erreur lors de l'agregation : %s", exc)

    result = {"n_total": total}
    for name in metric_names:
        vals = scores[name]
        result[f"{name}_mean"]        = round(sum(vals) / len(vals), 3) if vals else None
        result[f"{name}_pass_rate_%"] = round(passed[name] / max(total, 1) * 100, 1)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# MODE PYTEST — tests paramétrés par story
# ─────────────────────────────────────────────────────────────────────────────

def _load_latest_results(model_name: Optional[str]) -> Dict[str, List[Dict]]:
    """Charge le dernier fichier benchmark JSON."""
    files = sorted(RESULTS_DIR.glob("benchmark_llm_*.json"))
    if not files:
        return {}
    with open(files[-1], encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get("raw_results", {})
    if model_name:
        return {model_name: raw.get(model_name, [])} if model_name in raw else {}
    return raw


# Chargement des test cases au niveau module pour pytest
_pytest_api_key = os.getenv("GROQ_API_KEY_1", "")
_pytest_raw     = _load_latest_results(None)
_pytest_judge   = _build_groq_judge(_pytest_api_key) if _DEEPEVAL_AVAILABLE and _pytest_api_key else None
_pytest_metrics = build_metrics(_pytest_judge) if _pytest_judge else []

# Aplatit tous les test cases (tous modèles confondus) pour pytest
_all_test_cases: List[LLMTestCase] = []
for _model_name, _stories in _pytest_raw.items():
    _all_test_cases.extend(build_test_cases(_model_name, _stories))


try:
    import pytest

    @pytest.mark.parametrize("test_case", _all_test_cases)
    def test_user_story_improvement(test_case: "LLMTestCase"):
        """
        Test DeepEval : chaque story améliorée doit passer les 3 métriques.
        Lance avec : pytest test_llm_deepeval.py -v
        """
        assert _pytest_metrics, (
            "Aucune metrique disponible — verifier GROQ_API_KEY_1 et deepeval installe"
        )
        assert_test(test_case, _pytest_metrics)

except ImportError:
    pass   # pytest non disponible — mode standalone uniquement


# ─────────────────────────────────────────────────────────────────────────────
# MODE STANDALONE
# ─────────────────────────────────────────────────────────────────────────────

def _print_summary(summary: Dict[str, Any]) -> None:
    """Affiche le tableau de résultats DeepEval dans le terminal."""
    print("\n" + "=" * 70)
    print(f"  DEEPEVAL EVALUATION — {summary.get('model', '?')}")
    print("=" * 70)
    print(f"  Test cases evalues : {summary.get('n_total', 0)}")
    print()

    metric_keys = [
        ("GEval",             "GEval"),
        ("AnswerRelevancy",   "AnswerRelevancyMetric"),
        ("Faithfulness",      "FaithfulnessMetric"),
    ]
    for display, key in metric_keys:
        mean      = summary.get(f"{key}_mean")
        pass_rate = summary.get(f"{key}_pass_rate_%")
        if mean is not None:
            status = "[PASS]" if (pass_rate or 0) >= 50 else "[FAIL]"
            print(f"  {status} {display:<20} score={mean:.3f}  pass_rate={pass_rate:.1f}%")
        else:
            print(f"  [N/A]  {display}")
    print("=" * 70 + "\n")


async def main_async(args: argparse.Namespace) -> None:
    api_key = os.getenv("GROQ_API_KEY_1", "")
    if not api_key:
        print("[ERROR] GROQ_API_KEY_1 non trouvee dans .env")
        sys.exit(1)

    raw_stories: Optional[List[Dict]] = None
    model_name = args.model or _DEFAULT_MODEL_NAME

    if args.run_pipeline:
        # Lance le pipeline en direct pour générer les improved stories
        print(f"[PIPELINE] Lancement du pipeline sur {len(DATASET)} stories...")
        print(f"  Modele : {_DEFAULT_TEST_MODEL}\n")
        raw_stories = await run_pipeline(_DEFAULT_TEST_MODEL, api_key)
        model_name  = _DEFAULT_MODEL_NAME
    else:
        # Charge depuis les résultats existants du benchmark
        loaded = _load_latest_results(args.model)
        if not loaded:
            print("[ERROR] Aucun resultat benchmark trouve.")
            print("  Lancez d'abord :")
            print("  python -m app.ai_workflows.user_story_refinement.evaluation.benchmark_llm")
            sys.exit(1)
        # Prend le premier modèle disponible (ou celui filtré)
        model_name, raw_stories = next(iter(loaded.items()))

    if not raw_stories:
        print("[ERROR] Aucune story a evaluer.")
        sys.exit(1)

    summary = run_deepeval_evaluation(model_name, raw_stories, api_key, verbose=True)
    if summary:
        _print_summary(summary)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Suite de tests DeepEval pour le User Story Refinement pipeline"
    )
    parser.add_argument("--model", default=None,
                        help="Nom du modele a evaluer (ex: Llama-3.3-70B)")
    parser.add_argument("--run-pipeline", action="store_true",
                        help="Lance le pipeline LLM d'abord (sinon charge depuis benchmark JSON)")
    args = parser.parse_args()

    if not _DEEPEVAL_AVAILABLE:
        print("[ERROR] DeepEval non installe.")
        print("  pip install deepeval")
        sys.exit(1)

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
