"""
test_llm_deepeval.py — Suite de tests DeepEval pour le pipeline User Story Refinement.
... (docstring inchangée)
"""

from __future__ import annotations
import uuid
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
_DEFAULT_TEST_MODEL = "llama-3.3-70b-versatile"
_DEFAULT_MODEL_NAME = "Llama-3.3-70B"

# ─────────────────────────────────────────────────────────────────────────────
# DEEPEVAL — IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
try:
    import deepeval
    from deepeval import assert_test, evaluate
    from deepeval.metrics.base_metric import BaseMetric
    from deepeval.test_case import LLMTestCase
    from deepeval.dataset import EvaluationDataset
    try:
        from deepeval import login_with_confident_api_key
    except ImportError:
        try:
            from deepeval.confident.api import login_with_confident_api_key
        except ImportError:
            login_with_confident_api_key = getattr(deepeval, "login_with_confident_api_key", None)
    _DEEPEVAL_AVAILABLE = True
except ImportError as _deepeval_import_err:
    _DEEPEVAL_AVAILABLE = False
    print(f"[WARN] DeepEval import échoué : {_deepeval_import_err}")
    class BaseMetric: pass
    class LLMTestCase: pass

# ── Root Signals (correcteur) ─────────────────────────────────────────────────
try:
    from root import RootSignals as _RootSignals
    _ROOT_AVAILABLE = True
except ImportError:
    _ROOT_AVAILABLE = False
    print("[WARN] root-signals non installe. Installe avec : pip install root-signals")

# ─────────────────────────────────────────────────────────────────────────────
# PREDICATS (identiques à benchmark_llm.py)
# ─────────────────────────────────────────────────────────────────────────────
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

_RELEVANCY_PREDICATE = (
    "CONTEXT — PURPOSE:\n"
    "The improved story will be used to generate software test cases. "
    "The LLM's job is to clarify the original story, not to rewrite or expand it.\n\n"
    "Original story (input — what needs to be clarified): {{request}}\n\n"
    "Improved story (output — the LLM's clarification): {{response}}\n\n"
    "Score HIGH if the improved story:\n"
    "  - directly targets the ambiguities present in the original (vague terms, missing AC, "
    "no measurable conditions)\n"
    "  - adds only what is needed to remove ambiguity for testing purposes\n"
    "  - a QA engineer can now write test cases without any interpretation\n\n"
    "Score LOW if the improved story:\n"
    "  - ignores the original weaknesses and rewrites from scratch\n"
    "  - adds features or scope not present in the original\n"
    "  - is off-topic or still leaves ambiguity that blocks test writing"
)

_FAITHFULNESS_PREDICATE = (
    "CONTEXT — PURPOSE:\n"
    "These stories will be used to generate test cases. Modifying the business context "
    "would invalidate the original requirements. The LLM must ONLY clarify — never alter.\n\n"
    "Original story (the reference — must not be altered): {{request}}\n\n"
    "Improved story (the LLM's output): {{response}}\n\n"
    "Score HIGH if ALL of the following hold:\n"
    "  - Same actor/role (e.g. 'registered user' stays 'registered user')\n"
    "  - Same feature/action (e.g. 'reset password' stays 'reset password')\n"
    "  - Same business goal in 'so that' clause — only made more precise, not changed\n"
    "  - No new features, no removed features, no scope change\n"
    "  - A reader of the original would recognise the improved story as the same requirement\n\n"
    "Score LOW if:\n"
    "  - The actor was changed or renamed\n"
    "  - The feature or business goal was altered\n"
    "  - New requirements unrelated to the original were introduced\n"
    "  - The original intent was paraphrased into something different"
)

# ─────────────────────────────────────────────────────────────────────────────
# MÉTRIQUES
# ─────────────────────────────────────────────────────────────────────────────
def _make_metric_class(metric_name: str, evaluator_intent: str, evaluator_predicate: str):
    class _RootMetric(BaseMetric):
        _name     = metric_name
        _intent   = evaluator_intent
        _pred     = evaluator_predicate

        def __init__(self, api_key: str = "", threshold: float = 0.5):
            self._api_key  = api_key or os.getenv("ROOTSIGNALS_API_KEY", "")
            self.threshold = threshold
            self.score: Optional[float]  = None
            self.reason: Optional[str]   = None
            self.success: Optional[bool] = None
            self.async_mode = False

        def _run_sync(self, original: str, improved: str) -> float:
            client = _RootSignals(api_key=self._api_key)
            unique_name = f"{self._name}_{uuid.uuid4().hex[:8]}"
            evaluator = client.evaluators.create(
                name=unique_name,
                intent=self._intent,
                predicate=self._pred,
                model="gpt-4o",
            )
            result = evaluator.run(request=original, response=improved)
            return round(float(result.score), 3)

        def measure(self, test_case: "LLMTestCase") -> float:
            try:
                self.score   = self._run_sync(test_case.input, test_case.actual_output)
                self.success = self.score >= self.threshold
                self.reason  = ""
            except Exception as exc:
                logger.warning("[%s] measure failed: %s", self._name, exc)
                self.score   = 0.0
                self.success = False
                self.reason  = str(exc)
            return self.score

        async def a_measure(self, test_case: "LLMTestCase") -> float:
            try:
                self.score = await asyncio.to_thread(
                    self._run_sync, test_case.input, test_case.actual_output
                )
                self.success = self.score >= self.threshold
                self.reason  = ""
            except Exception as exc:
                logger.warning("[%s] a_measure failed: %s", self._name, exc)
                self.score   = 0.0
                self.success = False
                self.reason  = str(exc)
            return self.score

        def is_successful(self) -> bool:
            return bool(self.success)

    _RootMetric.__name__ = metric_name.replace(" ", "").replace("—", "")
    _RootMetric.__qualname__ = _RootMetric.__name__
    return _RootMetric

RootSignalsINVESTMetric = _make_metric_class(
    "TestForge — INVEST Quality",
    "Evaluate if improved user story is genuinely better per INVEST framework",
    _INVEST_PREDICATE,
)
RootSignalsRelevancyMetric = _make_metric_class(
    "TestForge — Answer Relevancy",
    "Evaluate if the improved story directly addresses the original story weaknesses",
    _RELEVANCY_PREDICATE,
)
RootSignalsFaithfulnessMetric = _make_metric_class(
    "TestForge — Faithfulness",
    "Evaluate if improved story preserves original role and business goal",
    _FAITHFULNESS_PREDICATE,
)

def build_metrics(root_api_key: str) -> List[Any]:
    if not _DEEPEVAL_AVAILABLE or not _ROOT_AVAILABLE or not root_api_key:
        return []
    return [
        RootSignalsINVESTMetric(root_api_key, threshold=0.5),
        RootSignalsRelevancyMetric(root_api_key, threshold=0.5),
        RootSignalsFaithfulnessMetric(root_api_key, threshold=0.5),
    ]

# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCTION DES TEST CASES
# ─────────────────────────────────────────────────────────────────────────────
def _invest_context(entry: Dict) -> str:
    issues = entry.get("expected_issues", [])
    issues_str = "\n".join(f"  - {i}" for i in issues) if issues else "  (none identified)"
    return (
        f"Original story: {entry['story']}\n"
        f"Category: {entry['category']} | Language: {entry['language']}\n"
        f"Known issues:\n{issues_str}"
    )

def build_test_cases(model_name: str, raw_stories: List[Dict]) -> List[LLMTestCase]:
    test_cases = []
    dataset_map = {e["id"]: e for e in DATASET}
    for s in raw_stories:
        if not s.get("success"):
            continue
        story_id = s["story_id"]
        entry    = dataset_map.get(story_id, {})
        category = s.get("category", "?")
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
        else:
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
# PIPELINE LLM
# ─────────────────────────────────────────────────────────────────────────────
class _ImprovementResult(BaseModel):
    improved_story: str = Field(description="The improved user story text")
    acceptance_criteria: List[str] = Field(description="Improved acceptance criteria list")
    reasoning: str = Field(description="What was changed and why")

async def _run_pipeline_for_entry(llm: Any, entry: Dict) -> Optional[Dict]:
    try:
        t0 = time.perf_counter()
        ac = await extract_acceptance_criteria(entry["story"], entry.get("acceptance_criteria", []))
        sr = await score_story(entry["story"], ac)
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
            "story_id": entry["id"], "category": entry["category"],
            "language": entry["language"], "success": True, "latency_s": latency,
            "initial_score": round(sr.get("score", 0), 3),
            "final_score": round(final_sr.get("score", 0), 3),
            "score_delta": round(final_sr.get("score", 0) - sr.get("score", 0), 3),
            "improved_story": result.improved_story,
            "acceptance_criteria": result.acceptance_criteria,
            "reasoning": result.reasoning,
        }
    except Exception as exc:
        logger.warning("[PIPELINE] %s failed: %s", entry["id"], exc)
        return {"story_id": entry["id"], "category": entry["category"],
                "language": entry["language"], "success": False, "error": str(exc)}

async def run_pipeline(model_id: str, api_key: str) -> List[Dict]:
    llm = ChatGroq(
        groq_api_key=api_key, model=model_id,
        temperature=LLM_TEMPERATURE, max_tokens=LLM_MAX_TOKENS,
    ).with_structured_output(_ImprovementResult)
    results = []
    for i, entry in enumerate(DATASET):
        print(f"  [{i+1}/{len(DATASET)}] {entry['id']} ...", end=" ", flush=True)
        r = await _run_pipeline_for_entry(llm, entry)
        status = "OK" if r and r.get("success") else "FAIL"
        print(status)
        results.append(r)
        await asyncio.sleep(2.0)
    return [r for r in results if r]

# ─────────────────────────────────────────────────────────────────────────────
# EVALUATION DEEPEVAL
# ─────────────────────────────────────────────────────────────────────────────
def _connect_confident_ai(confident_api_key: str) -> bool:
    if not _DEEPEVAL_AVAILABLE or not confident_api_key:
        return False
    if login_with_confident_api_key is None:
        os.environ["CONFIDENT_API_KEY"] = confident_api_key
        print("  [Confident AI] Clé définie via env (login_with_confident_api_key indisponible)")
        return True
    try:
        login_with_confident_api_key(confident_api_key)
        print("  [Confident AI] Connexion établie — résultats visibles sur app.confident-ai.com")
        return True
    except Exception as exc:
        print(f"  [Confident AI] Connexion échouée : {exc}")
        return False

def _aggregate_results(eval_results: Any, metrics: List[Any]) -> Dict[str, Any]:
    """Extrait les scores moyens et le taux de réussite par métrique.
    
    Approche robuste : lit les scores directement depuis les objets métriques
    après l'évaluation, plutôt que de parser la structure interne de DeepEval.
    """
    metric_names = [m.__class__.__name__ for m in metrics]
    scores: Dict[str, List[float]] = {n: [] for n in metric_names}
    passed: Dict[str, int] = {n: 0 for n in metric_names}
    total_success_count = 0
    
    # Parcourir les résultats de test pour compter le total
    try:
        for tc_result in eval_results.test_results:
            total_success_count += 1
    except Exception:
        pass
    
    # Lire les scores directement depuis les objets métriques (après évaluation)
    for i, m in enumerate(metrics):
        name = metric_names[i]
        if hasattr(m, 'score') and m.score is not None:
            scores[name].append(float(m.score))
            if m.is_successful():
                passed[name] += 1
    
    result = {"n_total": len(metrics[0]._test_cases_seen) if hasattr(metrics[0], '_test_cases_seen') else total_success_count}
    for name in metric_names:
        vals = scores[name]
        result[f"{name}_mean"] = round(sum(vals) / len(vals), 3) if vals else None
        result[f"{name}_pass_rate_%"] = round(passed[name] / max(result['n_total'], 1) * 100, 1)
    
    return result

def run_deepeval_evaluation(
    model_name: str, raw_stories: List[Dict], root_api_key: str,
    confident_api_key: str = "", verbose: bool = True,
) -> Dict[str, Any]:
    if not _DEEPEVAL_AVAILABLE:
        print("[WARN] DeepEval non disponible — evaluation ignoree.")
        return {}
    if confident_api_key:
        _connect_confident_ai(confident_api_key)
    
    print(f"\n[DEEPEVAL] Construction des test cases pour : {model_name}")
    test_cases = build_test_cases(model_name, raw_stories)
    print(f"  {len(test_cases)} test cases construits ({len(raw_stories)} stories)")
    
    metrics = build_metrics(root_api_key)
    if not metrics:
        print("[WARN] Aucune metrique disponible — verifier ROOTSIGNALS_API_KEY et root-signals installe.")
        return {}
    
    print(f"  Metriques : {[m.__class__.__name__ for m in metrics]}")
    print(f"  Correcteur : Root Signals Judge (RootSignals-Judge-Llama-70B)\n")
    
    # Exécuter l'évaluation
    eval_results = evaluate(test_cases=test_cases, metrics=metrics)
    
    # Agréger les résultats
    summary = _aggregate_results(eval_results, metrics)
    summary["model"] = model_name
    summary["n_test_cases"] = len(test_cases)
    
    # Sauvegarde JSON
    out_path = RESULTS_DIR / f"deepeval_{model_name.replace('/', '_')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] Resultats sauvegardes : {out_path}")
    
    return summary

# ─────────────────────────────────────────────────────────────────────────────
# MODE PYTEST
# ─────────────────────────────────────────────────────────────────────────────
def _load_latest_results(model_name: Optional[str]) -> Dict[str, List[Dict]]:
    files = sorted(RESULTS_DIR.glob("benchmark_llm_*.json"))
    if not files:
        return {}
    with open(files[-1], encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get("raw_results", {})
    if model_name:
        return {model_name: raw.get(model_name, [])} if model_name in raw else {}
    return raw

_pytest_root_key = os.getenv("ROOTSIGNALS_API_KEY", "")
_pytest_raw = _load_latest_results(None)
_pytest_metrics = build_metrics(_pytest_root_key) if _pytest_root_key else []
_all_test_cases: List[LLMTestCase] = []
for _model_name, _stories in _pytest_raw.items():
    _all_test_cases.extend(build_test_cases(_model_name, _stories))

try:
    import pytest
    @pytest.mark.parametrize("test_case", _all_test_cases)
    def test_user_story_improvement(test_case: "LLMTestCase"):
        assert _pytest_metrics, (
            "Aucune metrique disponible — verifier ROOTSIGNALS_API_KEY et root-signals installe"
        )
        assert_test(test_case, _pytest_metrics)
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# MODE STANDALONE
# ─────────────────────────────────────────────────────────────────────────────
def _print_summary(summary: Dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print(f"  DEEPEVAL EVALUATION — {summary.get('model', '?')}")
    print("=" * 70)
    print(f"  Test cases evalues : {summary.get('n_total', 0)}")
    print()
    metric_keys = [
        ("INVEST Quality", "RootSignalsINVESTMetric"),
        ("Answer Relevancy", "RootSignalsRelevancyMetric"),
        ("Faithfulness", "RootSignalsFaithfulnessMetric"),
    ]
    for display, key in metric_keys:
        mean = summary.get(f"{key}_mean")
        pass_rate = summary.get(f"{key}_pass_rate_%")
        if mean is not None:
            status = "[PASS]" if (pass_rate or 0) >= 50 else "[FAIL]"
            print(f"  {status} {display:<20} score={mean:.3f}  pass_rate={pass_rate:.1f}%")
        else:
            print(f"  [N/A]  {display}")
    print("=" * 70 + "\n")

async def main_async(args: argparse.Namespace) -> None:
    groq_api_key = os.getenv("GROQ_API_KEY_1", "")
    root_api_key = os.getenv("ROOTSIGNALS_API_KEY", "")
    confident_api_key = os.getenv("CONFIDENT_API_KEY", "") if args.confident else ""
    
    if not root_api_key:
        print("[ERROR] ROOTSIGNALS_API_KEY non trouvee dans .env")
        sys.exit(1)
    
    if args.confident and not confident_api_key:
        print("[WARN] --confident active mais CONFIDENT_API_KEY introuvable dans .env")
        print("  Les resultats ne seront pas envoyes au dashboard Confident AI.")
    
    raw_stories: Optional[List[Dict]] = None
    model_name = args.model or _DEFAULT_MODEL_NAME
    
    if args.run_pipeline:
        if not groq_api_key:
            print("[ERROR] GROQ_API_KEY_1 non trouvee dans .env (necessaire pour --run-pipeline)")
            sys.exit(1)
        print(f"[PIPELINE] Lancement du pipeline sur {len(DATASET)} stories...")
        print(f"  Modele : {_DEFAULT_TEST_MODEL}\n")
        raw_stories = await run_pipeline(_DEFAULT_TEST_MODEL, groq_api_key)
        model_name = _DEFAULT_MODEL_NAME
    else:
        loaded = _load_latest_results(args.model)
        if not loaded:
            print("[ERROR] Aucun resultat benchmark trouve.")
            print("  Lancez d'abord :")
            print("  python -m app.ai_workflows.user_story_refinement.evaluation.benchmark_llm")
            sys.exit(1)
        model_name, raw_stories = next(iter(loaded.items()))
    
    if not raw_stories:
        print("[ERROR] Aucune story a evaluer.")
        sys.exit(1)
    
    summary = run_deepeval_evaluation(
        model_name, raw_stories, root_api_key,
        confident_api_key=confident_api_key, verbose=True,
    )
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
    parser.add_argument("--confident", action="store_true",
                        help="Envoie les resultats au dashboard Confident AI (necessite CONFIDENT_API_KEY dans .env)")
    args = parser.parse_args()
    
    if not _DEEPEVAL_AVAILABLE:
        print("[ERROR] DeepEval non installe. pip install deepeval")
        sys.exit(1)
    if not _ROOT_AVAILABLE:
        print("[ERROR] root-signals non installe. pip install root-signals")
        sys.exit(1)
    
    asyncio.run(main_async(args))

if __name__ == "__main__":
    main()