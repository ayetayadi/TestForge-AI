"""
Risk Analysis Pipeline - ALIGNED WITH ORIGINAL DOCUMENT.

Simple 2-step process:
  1. LLM analyzes story and suggests P (1-5) + I (1-5)
  2. Compute risk_score = P × I, classify level
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Callable

from langsmith import traceable
from pydantic import BaseModel, Field
from app.ai_workflows.risk_analysis.risk_scorer import build_risk_record, get_test_depth
from app.ai_workflows.risk_analysis.prompts import RISK_ANALYSIS_PROMPT
from app.llm.llm_control import create_llm
from .config import LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


class RiskAnalysisOutput(BaseModel):
    """LLM output schema - All fields requested in the prompt."""
    
    probability: int = Field(
        description="Probability of failure: integer from 1 (very unlikely) to 5 (almost certain)"
    )
    impact: int = Field(
        description="Impact severity: integer from 1 (minimal) to 5 (business-critical)"
    )
    
    # Facteurs détaillés
    probability_factors: dict = Field(
        description="The 4 probability factors: story_complexity, ac_complexity, dependencies, clarity"
    )
    impact_factors: dict = Field(
        description="The 4 impact factors: users_affected, revenue, safety, reputation"
    )
    
    # Raisonnements
    probability_reasoning: str = Field(
        description="One sentence explaining P"
    )
    impact_reasoning: str = Field(
        description="One sentence explaining I"
    )
    
    # Description et mitigation
    description: str = Field(
        description="One short sentence describing the risk"
    )
    mitigation: str = Field(
        description="One concrete testing action"
    )
    
    # Raisonnement global
    reasoning: str = Field(
        description="Exactly 3 bullet points: why P, why I, calculation"
    )
    
    test_depth: Optional[str] = Field(
        default=None,
        description="comprehensive, thorough, standard, or smoke"
    )

def _normalize_llm_data(data: dict) -> dict:
    """Map LLM shorthand keys to the expected RiskAnalysisOutput field names."""
    # probability: accept P, prob, probability
    if "probability" not in data:
        for alias in ("P", "prob", "p"):
            if alias in data:
                data["probability"] = data.pop(alias)
                break

    # impact: accept I, imp, impact
    if "impact" not in data:
        for alias in ("I", "imp", "i"):
            if alias in data:
                data["impact"] = data.pop(alias)
                break

    # description: accept risk_description, risk_desc, risk
    if "description" not in data:
        for alias in ("risk_description", "risk_desc", "risk", "risk_summary"):
            if alias in data:
                data["description"] = data.pop(alias)
                break

    # reasoning: join if returned as a list
    if "reasoning" in data and isinstance(data["reasoning"], list):
        data["reasoning"] = "\n".join(str(line) for line in data["reasoning"])

    # probability_reasoning / impact_reasoning: tolerate missing with fallback
    if "probability_reasoning" not in data:
        data["probability_reasoning"] = ""
    if "impact_reasoning" not in data:
        data["impact_reasoning"] = ""

    # probability_factors / impact_factors: tolerate missing with defaults
    if "probability_factors" not in data:
        p = int(data.get("probability", 3))
        data["probability_factors"] = {
            "story_complexity": p, "ac_complexity": p,
            "dependencies": p, "clarity": p,
        }
    if "impact_factors" not in data:
        i = int(data.get("impact", 3))
        data["impact_factors"] = {
            "users_affected": i, "revenue": i,
            "safety": i, "reputation": i,
        }

    # mitigation: tolerate missing
    if "mitigation" not in data:
        data["mitigation"] = data.get("recommendation", data.get("test_recommendation", ""))

    return data


class RiskAnalysisPipeline:
    """Pipeline conforme au document Risk Based Testing original."""

    def __init__(self, temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL):
        logger.info("[RISK ANALYSIS] Initializing pipeline (document-aligned)...")
        llm = create_llm(temperature=temperature, model=model, max_tokens=LLM_MAX_TOKENS)
        self._llm = llm
        logger.info("[RISK ANALYSIS] Ready (P:1-5, I:1-5, Score:1-25)")

    async def _emit(self, callback: Optional[Callable], event_type: str, data: dict) -> None:
        if callback is None:
            return
        try:
            await callback(event_type, data)
        except Exception:
            pass

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
        acceptance_criteria = acceptance_criteria or []

        logger.info(f"[RISK ANALYSIS] Starting analysis for {issue_key}")

        try:
            # ── STEP 1: LLM RISK ASSESSMENT ────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "assessing",
                "message": "AI analyzing story for risk (P: 1-5, I: 1-5)...",
            })

            try:
                result: RiskAnalysisOutput = await asyncio.wait_for(
                    self._call_llm(story, acceptance_criteria, issue_key),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(f"[RISK ANALYSIS] LLM timed out after {LLM_TIMEOUT_SECONDS}s")
                raise RuntimeError("LLM call timed out")

            # ── STEP 2: COMPUTE SCORE & CLASSIFY ───────────────
            await self._emit(progress_callback, "phase", {
                "phase": "scoring",
                "message": f"Computing P({result.probability}) × I({result.impact})...",
            })

            risk_record = build_risk_record(
                probability=result.probability,
                impact=result.impact,
                description=result.description,
                mitigation=result.mitigation,
                reasoning=result.reasoning,
                probability_factors=result.probability_factors,
                impact_factors=result.impact_factors,
                probability_reasoning=result.probability_reasoning,
                impact_reasoning=result.impact_reasoning,
                test_depth=result.test_depth,       
                user_story_id=user_story_id,
                test_plan_id=test_plan_id,
            )

            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": (
                    f"Risk: P={risk_record['probability']} × I={risk_record['impact']} "
                    f"= {risk_record['risk_score']} ({risk_record['level'].upper()}) - "
                    f"Test depth: {risk_record['test_depth']}"
                ),
                "level": risk_record["level"],
                "risk_score": risk_record["risk_score"],
                "test_depth": risk_record["test_depth"],
            })

            logger.info(
                f"[RESULT] {issue_key} → "
                f"P={result.probability} I={result.impact} "
                f"Score={risk_record['risk_score']} Level={risk_record['level']}"
            )

            return {
                **risk_record,
                "issue_key": issue_key,
                "workflow_status": "success",
            }

        except Exception as exc:
            logger.error(f"[RISK ANALYSIS] Error: {exc}", exc_info=True)
            return {
                "user_story_id": user_story_id,
                "test_plan_id": test_plan_id,
                "description": f"Risk analysis failed: {str(exc)}",
                "mitigation": "",
                "probability": 3,
                "impact": 3,
                "risk_score": 9,
                "level": "medium",
                "test_depth": get_test_depth("medium"),
                "is_ai_generated": True,
                "is_accepted": None,
                "reasoning": "",
                "issue_key": issue_key,
                "workflow_status": "error",
                "error": str(exc),
            }

    
    async def _call_llm(
        self,
        story: str,
        acceptance_criteria: List[str],
        issue_key: str,
    ) -> RiskAnalysisOutput:
        import json
        import re
        
        ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria) if acceptance_criteria else "(none)"
        prompt = RISK_ANALYSIS_PROMPT.format(
            story=story,
            acceptance_criteria=ac_text,
            issue_key=issue_key,
        )
        
        prompt += "\n\nIMPORTANT: Respond with ONLY a valid JSON object. No other text before or after."
        
        try:
            response = await self._llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            content = content.strip()
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            
            data = json.loads(content)
            data = _normalize_llm_data(data)
            return RiskAnalysisOutput(**data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[RISK ANALYSIS] JSON parse failed for {issue_key}: {content[:300]}")
            raise RuntimeError(f"Failed to parse LLM response: {str(e)}")
        except Exception as e:
            logger.error(f"[RISK ANALYSIS] LLM call failed for {issue_key}: {str(e)}")
            raise

# ============================================================
# BATCH HELPER
# ============================================================

async def analyse_stories_batch(
    pipeline: RiskAnalysisPipeline,
    stories: List[Dict[str, Any]],
    test_plan_id: Optional[str] = None,
    concurrency: int = 3,
) -> List[Dict[str, Any]]:
    """Run risk analysis on multiple user stories concurrently."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_one(story_data: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            return await pipeline.run(
                story=story_data.get("story", ""),
                acceptance_criteria=story_data.get("acceptance_criteria", []),
                issue_key=story_data.get("issue_key", "?"),
                user_story_id=story_data.get("user_story_id"),
                test_plan_id=test_plan_id,
            )

    results = await asyncio.gather(*[_run_one(s) for s in stories], return_exceptions=False)
    return list(results)


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