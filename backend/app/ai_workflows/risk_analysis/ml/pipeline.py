"""
Pipeline — Orchestre le flux complet Risk-Based Testing.

Flux :
  1. Feature Extractor → prépare le texte
  2. ML Model → P (1-5), I (1-5), confiance
  3. Calculator → Score, Priorité, Effort
  4. LLM Explainer → Description, Mitigation, Reasoning
  5. Assemblage → RiskAnalysisResult
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any

from langsmith import traceable

from .config import (
    ML_CONFIDENCE_THRESHOLD,
    LLM_TEMPERATURE,
    LLM_MODEL,
    LLM_MAX_TOKENS,
    LLM_TIMEOUT_SECONDS,
)
from .models import (
    RiskAnalysisInput,
    RiskAnalysisResult,
    MLPrediction,
    LLMExplanation,
)
from .calculator import compute_full_result
from .ml_model import RiskMLModel
from .prompts import RBT_EXPLANATION_PROMPT, RISK_ANALYSIS_PROMPT_FALLBACK

logger = logging.getLogger(__name__)


class RiskAnalysisPipeline:
    """
    Pipeline complet d'analyse de risque basé sur le document RBT.

    Usage :
        pipeline = RiskAnalysisPipeline()
        await pipeline.initialize()  # Charge le modèle ML
        result = await pipeline.run(user_story, acceptance_criteria)
    """

    def __init__(self):
        self.ml_model = RiskMLModel()
        self._llm = None
        self._initialized = False

    async def initialize(self):
        """
        Initialise le pipeline : charge le modèle ML en mémoire.
        À appeler une fois au démarrage.
        """
        if not self._initialized:
            # Charger le modèle ML
            loaded = self.ml_model.load()
            if loaded:
                logger.info("Modèle ML chargé avec succès")
            else:
                logger.warning("Aucun modèle ML trouvé. Utilisation du fallback LLM.")

            # Initialiser le LLM (si disponible)
            try:
                from app.llm.llm_control import create_llm
                llm = create_llm(
                    temperature=LLM_TEMPERATURE,
                    model=LLM_MODEL,
                    max_tokens=LLM_MAX_TOKENS,
                )
                self._llm = llm.with_structured_output(LLMExplanation)
                logger.info("LLM initialisé")
            except Exception as e:
                logger.warning(f"LLM non disponible : {e}")
                self._llm = None

            self._initialized = True

    # ============================================================
    # ÉTAPE 1 : OBTENIR P ET I (ML → Fallback)
    # ============================================================

    async def _get_p_and_i(
        self, user_story: str, acceptance_criteria: List[str]
    ) -> MLPrediction:
        """
        Essaie d'obtenir P et I. Ordre : ML → LLM → Défaut.
        """
        combined_text = f"{user_story} {' '.join(acceptance_criteria)}"

        # --- Essai 1 : ML ---
        if self.ml_model.is_trained:
            try:
                prediction = self.ml_model.predict(combined_text)

                if prediction.confidence >= ML_CONFIDENCE_THRESHOLD:
                    logger.info(f"ML: P={prediction.probability}, I={prediction.impact}, conf={prediction.confidence}")
                    return prediction
                else:
                    logger.warning(f"Confiance ML trop basse ({prediction.confidence}), fallback LLM")

            except Exception as e:
                logger.error(f"Erreur ML : {e}")

        # --- Essai 2 : LLM ---
        if self._llm:
            try:
                logger.info("Fallback LLM pour P et I...")
                p, i = await self._ask_llm_for_pi(user_story, acceptance_criteria)
                return MLPrediction(probability=p, impact=i, confidence=0.5, source="llm_fallback")
            except Exception as e:
                logger.error(f"Erreur LLM fallback : {e}")

        # --- Essai 3 : Valeurs par défaut ---
        logger.warning("Aucun prédicteur disponible. Utilisation des valeurs par défaut.")
        return MLPrediction(probability=3, impact=3, confidence=0.0, source="default")

    
    async def _ask_llm_for_pi(
        self, user_story: str, acceptance_criteria: List[str]
    ) -> tuple:
        """Fallback LLM pour P et I."""
        from pydantic import BaseModel, Field
        
        class LLMPIFallback(BaseModel):
            probability: int = Field(ge=1, le=5)
            impact: int = Field(ge=1, le=5)
        
        # Créer un LLM temporaire avec ce schéma
        from app.llm.llm_control import create_llm
        llm_fallback = create_llm(
            temperature=0.1,
            model=LLM_MODEL,
            max_tokens=200,
        ).with_structured_output(LLMPIFallback)
        
        ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria)
        prompt = RISK_ANALYSIS_PROMPT_FALLBACK.format(
            story=user_story,
            acceptance_criteria=ac_text,
        )
        result = await asyncio.wait_for(
            llm_fallback.ainvoke(prompt),
            timeout=LLM_TIMEOUT_SECONDS,
        )
        return result.probability, result.impact

    # ============================================================
    # ÉTAPE 2 : GÉNÉRER L'EXPLICATION (LLM)
    # ============================================================

    async def _get_explanation(
        self,
        user_story: str,
        acceptance_criteria: List[str],
        probability: int,
        impact: int,
        risk_score: int,
        priority: str,
    ) -> LLMExplanation:
        """
        Demande au LLM d'expliquer le score (ne modifie pas P et I).
        """
        if not self._llm:
            # Fallback si LLM non disponible
            return LLMExplanation(
                description=f"Risk score: {risk_score}/25 ({priority})",
                mitigation="Validate with unit and integration tests",
                reasoning=f"P={probability}, I={impact} → Score={risk_score} ({priority})",
            )

        ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria) if acceptance_criteria else "(none)"

        prompt = RBT_EXPLANATION_PROMPT.format(
            probability=probability,
            impact=impact,
            risk_score=risk_score,
            priority=priority.upper(),
            user_story=user_story,
            acceptance_criteria=ac_text,
        )

        try:
            result = await asyncio.wait_for(
                self._llm.ainvoke(prompt),
                timeout=LLM_TIMEOUT_SECONDS,
            )
            if not isinstance(result, LLMExplanation):
                raise ValueError(f"LLM returned invalid type: {type(result)}")
            return result
        except asyncio.TimeoutError:
            logger.error("LLM explanation timed out")
            return LLMExplanation(
                description=f"Risk score: {risk_score}/{priority}",
                mitigation="Run standard test suite",
                reasoning=f"P={probability}, I={impact} → {risk_score}/25",
            )

    # ============================================================
    # FLUX PRINCIPAL
    # ============================================================

    @traceable(name="risk_analysis_pipeline")
    async def run(
        self,
        user_story: str,
        acceptance_criteria: List[str] = None,
        user_story_id: Optional[str] = None,
        test_plan_id: Optional[str] = None,
    ) -> RiskAnalysisResult:
        """
        Analyse le risque d'une User Story.

        Args:
            user_story : texte de la User Story
            acceptance_criteria : liste des critères d'acceptation
            user_story_id : ID optionnel en base
            test_plan_id : ID optionnel du plan de test

        Returns:
            RiskAnalysisResult complet
        """
        acceptance_criteria = acceptance_criteria or []

        if not self._initialized:
            await self.initialize()

        logger.info(f"Début analyse de risque pour US: {user_story[:80]}...")

        try:
            # ── Étape 1 : Obtenir P et I ──
            prediction = await self._get_p_and_i(user_story, acceptance_criteria)

            # ── Étape 2 : Calculer le score ──
            scorer_result = compute_full_result(
                probability=prediction.probability,
                impact=prediction.impact,
            )

            # ── Étape 3 : Générer l'explication ──
            explanation = await self._get_explanation(
                user_story=user_story,
                acceptance_criteria=acceptance_criteria,
                probability=scorer_result.probability,
                impact=scorer_result.impact,
                risk_score=scorer_result.risk_score,
                priority=scorer_result.priority,
            )

            # ── Étape 4 : Assembler le résultat ──
            result = RiskAnalysisResult(
                user_story_id=user_story_id,
                test_plan_id=test_plan_id,
                probability=scorer_result.probability,
                impact=scorer_result.impact,
                risk_score=scorer_result.risk_score,
                priority=scorer_result.priority,
                effort=scorer_result.effort,
                test_depth=scorer_result.test_depth,
                test_techniques=scorer_result.test_techniques,
                description=explanation.description,
                mitigation=explanation.mitigation,
                reasoning=explanation.reasoning,
                is_ai_generated=True,
                is_accepted=None,
                ml_confidence=prediction.confidence,
                source=prediction.source,
                workflow_status="success",
            )

            logger.info(
                f"Analyse terminée : P={result.probability}, I={result.impact}, "
                f"Score={result.risk_score}, Priorité={result.priority}, "
                f"Source={result.source}"
            )

            return result

        except Exception as e:
            logger.error(f"Erreur fatale dans le pipeline : {e}", exc_info=True)
            return RiskAnalysisResult(
                user_story_id=user_story_id,
                test_plan_id=test_plan_id,
                probability=3,
                impact=3,
                risk_score=9,
                priority="medium",
                effort=0.10,
                test_depth="standard",
                test_techniques=["unit", "integration"],
                description=f"Risk analysis failed: {str(e)}",
                mitigation="Review manually",
                reasoning="",
                is_ai_generated=False,
                is_accepted=None,
                ml_confidence=0.0,
                source="default",
                workflow_status="error",
                error=str(e),
            )


# ============================================================
# SINGLETON (optionnel)
# ============================================================

_instances: dict[str, "RiskAnalysisPipeline"] = {}


async def get_pipeline() -> "RiskAnalysisPipeline":
    from app.llm.llm_control import get_worker_api_key
    api_key = get_worker_api_key() or "default"
    if api_key not in _instances:
        logger.info(f"[RISK ML] Creating pipeline instance for key: {api_key[:12]}...")
        inst = RiskAnalysisPipeline()
        await inst.initialize()
        _instances[api_key] = inst
    return _instances[api_key]


def reset_pipeline():
    _instances.clear()
    logger.info("[RISK ML] All pipeline instances reset")


async def analyse_stories_batch(
    pipeline: RiskAnalysisPipeline,
    stories: List[Dict[str, Any]],
    test_plan_id: Optional[str] = None,
    concurrency: int = 3,
) -> List[Dict[str, Any]]:
    """
    Run risk analysis on a list of user story dicts concurrently.

    Each story dict must have at minimum: story (str), issue_key (str).
    Optional keys: acceptance_criteria, jira_priority, story_points, components, labels, epic, user_story_id.

    concurrency: max parallel LLM calls (keep ≤3 to avoid rate limits).
    """
    semaphore = asyncio.Semaphore(concurrency)