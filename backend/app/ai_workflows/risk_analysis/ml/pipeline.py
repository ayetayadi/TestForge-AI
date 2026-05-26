"""
Pipeline Risk Analysis — Orchestration complète.

Flux :
  1. NaiveBayesEmbedModel → P (1-5), I (1-5), confiance
  2. Calculator → Score, Priorité, Effort, Techniques
  3. LLM Explainer → Description, Mitigation, Reasoning
  4. Assemblage → RiskAnalysisResult
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any

from langsmith import traceable

from .config import ML_CONFIDENCE_THRESHOLD, LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS
from .models import RiskAnalysisInput, RiskAnalysisResult, MLPrediction, LLMExplanation
from .calculator import compute_full_result
from .nb_embed import KNNEmbedModel
from .prompts import RBT_EXPLANATION_PROMPT, RISK_ANALYSIS_PROMPT_FALLBACK

logger = logging.getLogger(__name__)


class RiskAnalysisPipeline:

    def __init__(self):
        self.ml_model = KNNEmbedModel()
        self._llm = None
        self._initialized = False

    async def initialize(self):
        if not self._initialized:
            loaded = self.ml_model.load()
            if loaded:
                logger.info("Modèle ML chargé avec succès")
            else:
                logger.warning("Aucun modèle ML trouvé. Fallback LLM.")

            try:
                from app.llm.llm_control import create_llm
                llm = create_llm(temperature=LLM_TEMPERATURE, model=LLM_MODEL, max_tokens=LLM_MAX_TOKENS)
                self._llm = llm.with_structured_output(LLMExplanation)
                logger.info("LLM initialisé")
            except Exception as e:
                logger.warning(f"LLM non disponible : {e}")
                self._llm = None

            self._initialized = True

    async def _get_p_and_i(self, user_story: str, acceptance_criteria: List[str]) -> MLPrediction:
        combined = f"{user_story} {' '.join(acceptance_criteria)}"

        if self.ml_model.is_trained:
            try:
                pred = self.ml_model.predict(combined)
                if pred.confidence >= ML_CONFIDENCE_THRESHOLD:
                    logger.info(f"ML: P={pred.probability}, I={pred.impact}, conf={pred.confidence}")
                    return pred
                logger.warning(f"Confiance ML basse ({pred.confidence}), fallback LLM")
            except Exception as e:
                logger.error(f"Erreur ML : {e}")

        if self._llm:
            try:
                p, i = await self._ask_llm_for_pi(user_story, acceptance_criteria)
                return MLPrediction(probability=p, impact=i, confidence=0.5, source="llm_fallback")
            except Exception as e:
                logger.error(f"Erreur LLM fallback : {e}")

        logger.warning("Aucun prédicteur disponible. Valeurs par défaut.")
        return MLPrediction(probability=3, impact=3, confidence=0.0, source="default")

    async def _ask_llm_for_pi(self, user_story: str, acceptance_criteria: List[str]) -> tuple:
        from pydantic import BaseModel, Field

        class LLMPIFallback(BaseModel):
            probability: int = Field(ge=1, le=5)
            impact: int = Field(ge=1, le=5)

        from app.llm.llm_control import create_llm
        llm_pi = create_llm(temperature=0.1, model=LLM_MODEL, max_tokens=200).with_structured_output(LLMPIFallback)

        ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria)
        prompt = RISK_ANALYSIS_PROMPT_FALLBACK.format(story=user_story, acceptance_criteria=ac_text)
        result = await asyncio.wait_for(llm_pi.ainvoke(prompt), timeout=LLM_TIMEOUT_SECONDS)
        return result.probability, result.impact

    async def _get_explanation(
        self, user_story: str, acceptance_criteria: List[str],
        probability: int, impact: int, risk_score: int, priority: str,
    ) -> LLMExplanation:
        if not self._llm:
            return LLMExplanation(
                description=f"Risk score: {risk_score}/25 ({priority})",
                mitigation="Validate with unit and integration tests",
                reasoning=f"P={probability}, I={impact} → Score={risk_score} ({priority})",
            )

        ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria) if acceptance_criteria else "(none)"
        prompt = RBT_EXPLANATION_PROMPT.format(
            probability=probability, impact=impact,
            risk_score=risk_score, priority=priority.upper(),
            user_story=user_story, acceptance_criteria=ac_text,
        )

        try:
            result = await asyncio.wait_for(self._llm.ainvoke(prompt), timeout=LLM_TIMEOUT_SECONDS)
            if not isinstance(result, LLMExplanation):
                raise ValueError(f"Type inattendu : {type(result)}")
            return result
        except asyncio.TimeoutError:
            logger.error("LLM timeout")
            return LLMExplanation(
                description=f"Risk score: {risk_score}/25 ({priority})",
                mitigation="Run standard test suite",
                reasoning=f"P={probability}, I={impact} → {risk_score}/25",
            )

    @traceable(name="risk_analysis_workflow")
    async def run(
        self,
        user_story: str,
        acceptance_criteria: List[str] = None,
        user_story_id: Optional[str] = None,
        test_plan_id: Optional[str] = None,
    ) -> RiskAnalysisResult:
        acceptance_criteria = acceptance_criteria or []

        if not self._initialized:
            await self.initialize()

        logger.info(f"Analyse de risque : {user_story[:80]}...")

        try:
            prediction = await self._get_p_and_i(user_story, acceptance_criteria)
            scorer = compute_full_result(prediction.probability, prediction.impact)
            explanation = await self._get_explanation(
                user_story=user_story,
                acceptance_criteria=acceptance_criteria,
                probability=scorer.probability,
                impact=scorer.impact,
                risk_score=scorer.risk_score,
                priority=scorer.priority,
            )

            result = RiskAnalysisResult(
                user_story_id=user_story_id,
                test_plan_id=test_plan_id,
                probability=scorer.probability,
                impact=scorer.impact,
                risk_score=scorer.risk_score,
                priority=scorer.priority,
                effort=scorer.effort,
                test_depth=scorer.test_depth,
                test_techniques=scorer.test_techniques,
                description=explanation.description,
                mitigation=explanation.mitigation,
                reasoning=explanation.reasoning,
                is_ai_generated=True,
                is_accepted=None,
                ml_confidence=prediction.confidence,
                source=prediction.source,
                workflow_status="success",
            )

            logger.info(f"Résultat : P={result.probability}, I={result.impact}, Score={result.risk_score}, Priorité={result.priority}")
            return result

        except Exception as e:
            logger.error(f"Erreur pipeline : {e}", exc_info=True)
            return RiskAnalysisResult(
                user_story_id=user_story_id,
                test_plan_id=test_plan_id,
                probability=3, impact=3, risk_score=9, priority="medium",
                effort=0.10, test_depth="standard", test_techniques=["unit", "integration"],
                description=f"Risk analysis failed: {str(e)}",
                mitigation="Review manually", reasoning="",
                is_ai_generated=False, is_accepted=None,
                ml_confidence=0.0, source="default",
                workflow_status="error", error=str(e),
            )


# ── Singleton ──────────────────────────────────────────────────

_instances: dict[str, "RiskAnalysisPipeline"] = {}


async def get_pipeline() -> "RiskAnalysisPipeline":
    from app.llm.llm_control import get_worker_api_key
    api_key = get_worker_api_key() or "default"
    if api_key not in _instances:
        inst = RiskAnalysisPipeline()
        await inst.initialize()
        _instances[api_key] = inst
    return _instances[api_key]


def reset_pipeline():
    _instances.clear()
    logger.info("[RISK ML] Pipeline réinitialisé")


async def analyse_stories_batch(
    pipeline: RiskAnalysisPipeline,
    stories: List[Dict[str, Any]],
    test_plan_id: Optional[str] = None,
    concurrency: int = 3,
) -> List[Dict[str, Any]]:
    """Analyse un lot de user stories en parallèle (max `concurrency` appels simultanés)."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _analyse_one(story: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            result = await pipeline.run(
                user_story=story.get("story", ""),
                acceptance_criteria=story.get("acceptance_criteria", []),
                user_story_id=story.get("user_story_id"),
                test_plan_id=test_plan_id,
            )
            return {**story, "risk_analysis": result.model_dump()}

    return await asyncio.gather(*[_analyse_one(s) for s in stories])
