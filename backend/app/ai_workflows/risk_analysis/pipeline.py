"""
 Risk Analysis Pipeline.

3 steps
  1. estimate_baseline(signals)     → derive P/I hints from Jira metadata
  2. LLM call                       → AI analyzes story and suggests P (float) + I (int)
  3. build_risk_record(P, I, ...)   → clamp, compute P×I, classify level, return dict
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langsmith import traceable
from pydantic import BaseModel, Field
from app.ai_workflows.risk_analysis.risk_scorer import estimate_baseline, build_risk_record
from app.ai_workflows.risk_analysis.prompts import RISK_ANALYSIS_PROMPT
from app.llm.llm_control import create_llm
from .config import LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


# ============================================================
# LLM OUTPUT SCHEMA
# ============================================================

class RiskAnalysisOutput(BaseModel):
    probability: float = Field(
        description="Probability of defect occurrence: float from 0.1 (very unlikely) to 0.9 (almost certain)"
    )
    impact: int = Field(
        description="Impact severity if the defect reaches production: integer from 1 (cosmetic) to 5 (business-critical)"
    )
    description: str = Field(
        description="1-2 sentences describing the specific risk identified in this user story"
    )
    mitigation: str = Field(
        description="1-2 concrete testing actions to reduce this risk"
    )
    reasoning: str = Field(
        description="Step-by-step justification of the P and I values (3-5 sentences)"
    )


# ============================================================
# PIPELINE
# ============================================================

class RiskAnalysisPipeline:
    """
     — Analyse des risques produit pour une User Story.

    Step 1 — estimate_baseline: extract Jira signals (story_points, priority, ac_count, components)
    Step 2 — LLM: suggest probability (0.1–0.9) and impact (1–5) with reasoning
    Step 3 — build_risk_record: clamp, compute risk_score = P×I, classify level
    """

    def __init__(self, temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL):
        logger.info("[RISK ANALYSIS] Initializing pipeline...")
        llm = create_llm(temperature=temperature, model=model, max_tokens=LLM_MAX_TOKENS)
        self._llm = llm.with_structured_output(RiskAnalysisOutput)
        logger.info("[RISK ANALYSIS] Ready")

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
        jira_priority: Optional[str] = None,
        story_points: Optional[float] = None,
        components: List[str] = None,
        labels: List[str] = None,
        epic: Optional[str] = None,
        issue_key: str = "?",
        user_story_id: Optional[str] = None,
        test_plan_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        acceptance_criteria = acceptance_criteria or []
        components = components or []
        labels = labels or []

        logger.info(f"[RISK ANALYSIS] Starting: issue_key={issue_key} priority={jira_priority} sp={story_points}")

        try:
            # ── STEP 1: BASELINE FROM SIGNALS ──────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "analyzing",
                "message": "Extracting risk signals from Jira metadata...",
            })

            baseline = estimate_baseline(
                jira_priority=jira_priority,
                story_points=story_points,
                ac_count=len(acceptance_criteria),
                components=components,
            )

            # ── STEP 2: LLM RISK ASSESSMENT ────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "assessing",
                "message": "AI analyzing story for risk factors (P × I)...",
            })

            try:
                result: RiskAnalysisOutput = await asyncio.wait_for(
                    self._call_llm(
                        story=story,
                        acceptance_criteria=acceptance_criteria,
                        jira_priority=jira_priority or "medium",
                        story_points=story_points,
                        components=components,
                        labels=labels,
                        epic=epic or "",
                        issue_key=issue_key,
                    ),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(f"[RISK ANALYSIS] LLM timed out after {LLM_TIMEOUT_SECONDS}s")
                raise RuntimeError("LLM call timed out")

            # ── STEP 3: COMPUTE SCORE & CLASSIFY ───────────────
            await self._emit(progress_callback, "phase", {
                "phase": "scoring",
                "message": "Computing risk score and classifying level...",
            })

            risk_record = build_risk_record(
                probability=result.probability,
                impact=result.impact,
                description=result.description,
                mitigation=result.mitigation,
                user_story_id=user_story_id,
                test_plan_id=test_plan_id,
                reasoning=result.reasoning,
            )

            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": (
                    f"Risk assessed: P={risk_record['probability']} × I={risk_record['impact']} "
                    f"= {risk_record['risk_score']} ({risk_record['level'].upper()})"
                ),
                "level": risk_record["level"],
                "risk_score": risk_record["risk_score"],
            })

            self._log_summary(issue_key, risk_record, baseline)

            return {
                **risk_record,
                "baseline_signals": baseline["signals"],
                "issue_key": issue_key,
                "workflow_status": "success",
            }

        except Exception as exc:
            logger.error(f"[RISK ANALYSIS] Fatal error: {exc}", exc_info=True)
            return {
                "user_story_id": user_story_id,
                "test_plan_id": test_plan_id,
                "description": f"Risk analysis failed: {str(exc)}",
                "mitigation": "",
                "probability": 0.5,
                "impact": 3,
                "risk_score": 1.5,
                "level": "moyenne",
                "is_ai_generated": True,
                "is_accepted": None,
                "reasoning": "",
                "baseline_signals": [],
                "issue_key": issue_key,
                "workflow_status": "error",
                "error": str(exc),
            }

    async def _call_llm(
        self,
        story: str,
        acceptance_criteria: List[str],
        jira_priority: str,
        story_points: Optional[float],
        components: List[str],
        labels: List[str],
        epic: str,
        issue_key: str,
    ) -> RiskAnalysisOutput:
        ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria) if acceptance_criteria else "(none)"
        prompt = RISK_ANALYSIS_PROMPT.format(
            story=story,
            acceptance_criteria=ac_text,
            issue_key=issue_key,
            jira_priority=jira_priority,
            story_points=story_points if story_points is not None else "N/A",
            components=", ".join(components) if components else "none",
            labels=", ".join(labels) if labels else "none",
            epic=epic or "none",
        )
        return await self._llm.ainvoke(prompt)

    def _log_summary(
        self,
        issue_key: str,
        risk: Dict[str, Any],
        baseline: Dict[str, Any],
    ) -> None:
        logger.info(
            f"[RESULT] issue={issue_key} "
            f"P={risk['probability']} I={risk['impact']} "
            f"score={risk['risk_score']} level={risk['level']} "
            f"baseline_P={baseline['probability_hint']} baseline_I={baseline['impact_hint']}"
        )


# ============================================================
# BATCH HELPER — analyse plusieurs US d'un coup
# ============================================================

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

    async def _run_one(story_data: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            return await pipeline.run(
                story=story_data.get("story", ""),
                acceptance_criteria=story_data.get("acceptance_criteria", []),
                jira_priority=story_data.get("jira_priority"),
                story_points=story_data.get("story_points"),
                components=story_data.get("components", []),
                labels=story_data.get("labels", []),
                epic=story_data.get("epic"),
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
