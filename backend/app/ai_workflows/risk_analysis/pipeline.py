"""
Risk Analysis Pipeline — ISTQB Risk-Based Testing.

Architecture:
  - Uses Groq structured output (with_structured_output) → zero JSON parsing
  - Flat Pydantic schema — sub-factors as plain ints, no nested dicts
  - P and I computed in Python from sub-factors (not by the LLM)
  - 1-2 scenarios per story; one Risk DB record per scenario
  - ~800 tokens total per call (70% less than freeform JSON approach)
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langsmith import traceable
from pydantic import BaseModel, Field

from app.ai_workflows.risk_analysis.risk_scorer import build_risk_record, get_test_depth
from app.ai_workflows.risk_analysis.prompts import RISK_ANALYSIS_PROMPT
from app.llm.llm_control import create_llm
from .config import LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


# ============================================================
# OUTPUT SCHEMA  — flat integers + two short strings
# No nested dicts, no reasoning strings → minimal token usage.
# P and I are derived in Python from the 8 sub-factor fields.
# ============================================================

class RiskScenario(BaseModel):
    """One risk scenario — all sub-factors as plain 1-5 integers."""
    scenario: str = Field(description="Risk name, max 8 words")

    # Probability sub-factors
    story_complexity: int = Field(ge=1, le=5)
    ac_complexity:    int = Field(ge=1, le=5)
    dependencies:     int = Field(ge=1, le=5)
    clarity:          int = Field(ge=1, le=5)

    # Impact sub-factors
    users_affected: int = Field(ge=1, le=5)
    revenue:        int = Field(ge=1, le=5)
    safety:         int = Field(ge=1, le=5)
    reputation:     int = Field(ge=1, le=5)

    description: str = Field(description="What fails and when, ≤20 words")
    mitigation:  str = Field(description="Test action starting with a verb, ≤15 words")


class MultiRiskOutput(BaseModel):
    """1-2 distinct risk scenarios per user story."""
    risks: List[RiskScenario] = Field(min_length=1, max_length=2)


# ============================================================
# PIPELINE
# ============================================================

class RiskAnalysisPipeline:
    """
    ISTQB Risk-Based Testing pipeline.
    Uses Groq structured output — no JSON parsing, no truncation risk.
    """

    def __init__(self, temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL):
        logger.info("[RISK ANALYSIS] Initializing pipeline (structured output)...")
        llm = create_llm(temperature=temperature, model=model, max_tokens=LLM_MAX_TOKENS)
        self._llm = llm.with_structured_output(MultiRiskOutput)
        logger.info(f"[RISK ANALYSIS] Ready — model={model}, max_tokens={LLM_MAX_TOKENS}")

    async def _emit(self, callback: Optional[Callable], event_type: str, data: dict) -> None:
        if callback is None:
            return
        try:
            await callback(event_type, data)
        except Exception:
            pass

    @staticmethod
    def _scenario_to_record(scenario: RiskScenario, user_story_id: str, test_plan_id: Optional[str]) -> Dict[str, Any]:
        """
        Convert a RiskScenario to a risk record dict.
        P = round(avg of 4 probability sub-factors)
        I = round(avg of 4 impact sub-factors)
        """
        p_factors = {
            "story_complexity": scenario.story_complexity,
            "ac_complexity":    scenario.ac_complexity,
            "dependencies":     scenario.dependencies,
            "clarity":          scenario.clarity,
        }
        i_factors = {
            "users_affected": scenario.users_affected,
            "revenue":        scenario.revenue,
            "safety":         scenario.safety,
            "reputation":     scenario.reputation,
        }

        p_reasoning = (
            f"P sub-factors: story_complexity={scenario.story_complexity}, "
            f"ac_complexity={scenario.ac_complexity}, "
            f"dependencies={scenario.dependencies}, "
            f"clarity={scenario.clarity}"
        )
        i_reasoning = (
            f"I sub-factors: users_affected={scenario.users_affected}, "
            f"revenue={scenario.revenue}, "
            f"safety={scenario.safety}, "
            f"reputation={scenario.reputation}"
        )

        record = build_risk_record(
            probability=3,          # overridden by sub-factor avg in build_risk_record
            impact=3,               # overridden by sub-factor avg in build_risk_record
            description=scenario.description,
            mitigation=scenario.mitigation,
            reasoning="",
            probability_factors=p_factors,
            impact_factors=i_factors,
            probability_reasoning=p_reasoning,
            impact_reasoning=i_reasoning,
            user_story_id=user_story_id,
            test_plan_id=test_plan_id,
        )
        record["scenario"] = scenario.scenario
        return record

    @traceable(name="risk_analysis_pipeline")
    async def run(
        self,
        story: str,
        acceptance_criteria: List[str] = None,
        issue_key: str = "?",
        user_story_id: Optional[str] = None,
        test_plan_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a user story and return 1-2 risk records.

        Returns:
            {
                "risks": [risk_record, ...],
                "issue_key": str,
                "workflow_status": "success" | "error",
            }
        """
        acceptance_criteria = acceptance_criteria or []
        logger.info(f"[RISK ANALYSIS] Starting: {issue_key}")

        try:
            await self._emit(progress_callback, "phase", {
                "phase": "assessing",
                "message": f"Identifying risk scenarios for {issue_key}...",
            })

            ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria) if acceptance_criteria else "(none)"
            prompt = RISK_ANALYSIS_PROMPT.format(
                story=story,
                acceptance_criteria=ac_text,
            )

            try:
                result: MultiRiskOutput = await asyncio.wait_for(
                    self._llm.ainvoke(prompt),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                raise RuntimeError(f"LLM timed out after {LLM_TIMEOUT_SECONDS}s")

            await self._emit(progress_callback, "phase", {
                "phase": "scoring",
                "message": f"Computing P×I for {len(result.risks)} scenario(s)...",
            })

            risk_records = [
                self._scenario_to_record(s, user_story_id, test_plan_id)
                for s in result.risks
            ]

            for r in risk_records:
                logger.info(
                    f"[RESULT] {issue_key} '{r['scenario']}' "
                    f"P={r['probability']} I={r['impact']} "
                    f"Score={r['risk_score']} Level={r['level']}"
                )

            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": (
                    f"{len(risk_records)} scenario(s) — "
                    f"highest: {max(r['level'] for r in risk_records)}"
                ),
                "risk_count": len(risk_records),
                "levels": [r["level"] for r in risk_records],
            })

            return {
                "risks": risk_records,
                "issue_key": issue_key,
                "workflow_status": "success",
            }

        except Exception as exc:
            logger.error(f"[RISK ANALYSIS] Error for {issue_key}: {exc}", exc_info=True)
            fallback = {
                "user_story_id": user_story_id,
                "test_plan_id": test_plan_id,
                "scenario": "Analysis failed",
                "description": f"Risk analysis failed: {str(exc)[:120]}",
                "mitigation": "",
                "probability": 3,
                "impact": 3,
                "risk_score": 9,
                "level": "high",
                "test_depth": get_test_depth("high"),
                "is_ai_generated": True,
                "is_accepted": None,
                "reasoning": "",
                "probability_factors": None,
                "impact_factors": None,
                "probability_reasoning": "",
                "impact_reasoning": "",
            }
            return {
                "risks": [fallback],
                "issue_key": issue_key,
                "workflow_status": "error",
                "error": str(exc),
            }


# ============================================================
# SINGLETON
# ============================================================

_instance: Optional[RiskAnalysisPipeline] = None


def get_pipeline(temperature: float = LLM_TEMPERATURE) -> RiskAnalysisPipeline:
    global _instance
    if _instance is None:
        _instance = RiskAnalysisPipeline(temperature=temperature)
    return _instance


def reset_pipeline() -> None:
    global _instance
    _instance = None
    logger.info("[RISK ANALYSIS] Singleton reset")
