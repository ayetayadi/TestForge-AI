"""
LLM pipeline for Test Case Design (ISTQB §5.4).

Workflow (4 fixed steps — no agent loop):
  1. analyze_story(story, ac)       → extract behaviors and boundary hints
  2. LLM call                       → generate Gherkin test cases (structured output)
  3. validate_ac_coverage(tcs, ac)  → verify ≥80% of ACs are covered
  4. finalize(tcs)                  → assign tc_codes, sort by type, set execution_order
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langsmith import traceable
from pydantic import BaseModel, Field

from app.ai_workflows.test_design.evaluators import (
    analyze_story,
    validate_ac_coverage,
    compute_tc_codes,
)
from app.ai_workflows.test_design.prompts import TEST_GENERATION_PROMPT
from app.llm.llm_control import create_llm
from .config import (
    LLM_TEMPERATURE,
    LLM_MODEL,
    LLM_MAX_TOKENS,
    LLM_TIMEOUT_SECONDS,
    RISK_LEVEL_TEST_COUNTS,
)

logger = logging.getLogger(__name__)


# ============================================================
# LLM OUTPUT SCHEMA
# ============================================================

class StepOutput(BaseModel):
    order: int = Field(description="Step number starting at 1")
    action: str = Field(description="What the tester does")
    expected: str = Field(description="Expected observable result")


class TestCaseOutput(BaseModel):
    title: str = Field(description="Short descriptive title")
    test_type: str = Field(description="positive | negative | edge_case")
    priority: str = Field(description="critical | high | medium | low")
    preconditions: List[str] = Field(default_factory=list, description="Required pre-conditions")
    gherkin_scenario: str = Field(description="Full Gherkin scenario (Given/When/Then)")
    steps: List[StepOutput] = Field(default_factory=list, description="Structured test steps")
    expected_results: List[str] = Field(default_factory=list, description="Final expected outcomes")
    tags: List[str] = Field(default_factory=list, description="Classification tags")
    test_data: Optional[Dict[str, Any]] = Field(default=None, description="Sample test data values")
    reasoning: str = Field(description="Which AC or behavior this test covers and why")


class TestDesignOutput(BaseModel):
    test_cases: List[TestCaseOutput] = Field(description="Generated test cases")
    coverage_note: str = Field(description="Brief summary of AC coverage")


# ============================================================
# TYPE ORDER FOR SORTING
# ============================================================

_TYPE_ORDER = {"positive": 0, "negative": 1, "edge_case": 2}


# ============================================================
# PIPELINE
# ============================================================

class TestDesignPipeline:
    """
    4-step LLM pipeline for generating Gherkin test cases from a user story.

    Step 1 — analyze story to extract behaviors and boundary hints
    Step 2 — LLM generates test cases (one call, structured output)
    Step 3 — validate AC coverage (≥80%)
    Step 4 — assign tc_codes, sort, and set execution_order
    """

    def __init__(self, temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL):
        logger.info("[TEST DESIGN] Initializing pipeline...")
        llm = create_llm(temperature=temperature, model=model, max_tokens=LLM_MAX_TOKENS)
        self._llm = llm.with_structured_output(TestDesignOutput)
        logger.info("[TEST DESIGN] Ready")

    async def _emit(self, callback: Optional[Callable], event_type: str, data: dict) -> None:
        if callback is None:
            return
        try:
            await callback(event_type, data)
        except Exception:
            pass

    @traceable(name="test_design_pipeline")
    async def run(
        self,
        story: str,
        acceptance_criteria: List[str] = None,
        risk_level: str = "moyenne",
        user_story_id: Optional[str] = None,
        jira_id: str = "?",
        tc_start_index: int = 1,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        acceptance_criteria = acceptance_criteria or []
        risk_level = risk_level.lower()
        counts = RISK_LEVEL_TEST_COUNTS.get(risk_level, RISK_LEVEL_TEST_COUNTS["default"])
        total_count = counts["positive"] + counts["negative"] + counts["edge_case"]

        logger.info(
            f"[TEST DESIGN] Starting: jira_id={jira_id} risk={risk_level} "
            f"total_tc={total_count} ac_count={len(acceptance_criteria)}"
        )

        try:
            # ── PHASE 1: ANALYZING ──────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "analyzing",
                "message": "Analyzing story behaviors and boundaries...",
            })

            analysis = await analyze_story(story, acceptance_criteria)

            # ── PHASE 2: GENERATING ──────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "generating",
                "message": f"Generating {total_count} test cases (risk: {risk_level})...",
            })

            try:
                result: TestDesignOutput = await asyncio.wait_for(
                    self._call_llm(story, acceptance_criteria, risk_level, counts, total_count),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(f"[TEST DESIGN] LLM timed out after {LLM_TIMEOUT_SECONDS}s")
                raise RuntimeError("LLM call timed out")

            raw_tcs = [tc.model_dump() for tc in result.test_cases]

            # ── PHASE 3: VALIDATING ──────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "validating",
                "message": "Validating acceptance criteria coverage...",
            })

            coverage = await validate_ac_coverage(raw_tcs, acceptance_criteria)

            if not coverage["is_sufficient"]:
                logger.warning(
                    f"[TEST DESIGN] Coverage {coverage['coverage_pct']:.0%} below threshold — "
                    f"uncovered: {coverage['uncovered_acs']}"
                )

            # ── PHASE 4: FINALIZING ──────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "finalizing",
                "message": "Assigning codes and ordering test cases...",
            })

            finalized = self._finalize(raw_tcs, user_story_id, tc_start_index)

            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": f"Generated {len(finalized)} test cases. Coverage: {coverage['coverage_pct']:.0%}",
                "count": len(finalized),
                "coverage_pct": coverage["coverage_pct"],
            })

            self._log_summary(jira_id, risk_level, finalized, coverage)
            return {
                "test_cases": finalized,
                "count": len(finalized),
                "risk_level": risk_level,
                "coverage_pct": coverage["coverage_pct"],
                "coverage_sufficient": coverage["is_sufficient"],
                "uncovered_acs": coverage["uncovered_acs"],
                "coverage_note": result.coverage_note,
                "analysis": analysis,
                "jira_id": jira_id,
                "user_story_id": user_story_id,
                "workflow_status": "success",
            }

        except Exception as exc:
            logger.error(f"[TEST DESIGN] Fatal error: {exc}", exc_info=True)
            return {
                "test_cases": [],
                "count": 0,
                "risk_level": risk_level,
                "coverage_pct": 0.0,
                "coverage_sufficient": False,
                "uncovered_acs": acceptance_criteria,
                "coverage_note": "",
                "analysis": {},
                "jira_id": jira_id,
                "user_story_id": user_story_id,
                "workflow_status": "error",
                "error": str(exc),
            }

    async def _call_llm(
        self,
        story: str,
        acceptance_criteria: List[str],
        risk_level: str,
        counts: Dict[str, int],
        total_count: int,
    ) -> TestDesignOutput:
        ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria) if acceptance_criteria else "(none)"
        prompt = TEST_GENERATION_PROMPT.format(
            story=story,
            acceptance_criteria=ac_text,
            risk_level=risk_level.upper(),
            count_positive=counts["positive"],
            count_negative=counts["negative"],
            count_edge_case=counts["edge_case"],
            total_count=total_count,
        )
        return await self._llm.ainvoke(prompt)

    def _finalize(
        self,
        test_cases: List[Dict[str, Any]],
        user_story_id: Optional[str],
        start_index: int,
    ) -> List[Dict[str, Any]]:
        sorted_tcs = sorted(test_cases, key=lambda tc: _TYPE_ORDER.get(tc.get("test_type", ""), 99))
        coded = compute_tc_codes(sorted_tcs, start_index)

        finalized = []
        for order, tc in enumerate(coded, start=1):
            # Convert StepOutput dicts if they have 'order/action/expected' keys
            steps = []
            for s in tc.get("steps", []):
                if isinstance(s, dict):
                    steps.append({"order": s.get("order", order), "action": s.get("action", ""), "expected": s.get("expected", "")})

            finalized.append({
                "tc_code": tc["tc_code"],
                "title": tc.get("title", ""),
                "test_type": tc.get("test_type", "positive"),
                "priority": tc.get("priority", "medium"),
                "preconditions": tc.get("preconditions", []),
                "gherkin_source": tc.get("gherkin_scenario", ""),
                "steps": steps,
                "expected_results": tc.get("expected_results", []),
                "tags": tc.get("tags", []),
                "test_data": tc.get("test_data"),
                "risk_ids": [],
                "user_story_id": user_story_id,
                "execution_order": order,
                "is_active": True,
            })

        return finalized

    def _log_summary(
        self,
        jira_id: str,
        risk_level: str,
        test_cases: List[Dict[str, Any]],
        coverage: Dict[str, Any],
    ) -> None:
        type_counts = {}
        for tc in test_cases:
            t = tc.get("test_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        logger.info(
            f"[RESULT] jira={jira_id} risk={risk_level} total={len(test_cases)} "
            f"types={type_counts} coverage={coverage['coverage_pct']:.0%}"
        )


# ============================================================
# SINGLETON
# ============================================================

_instance: Optional[TestDesignPipeline] = None


def get_pipeline(temperature: float = LLM_TEMPERATURE) -> TestDesignPipeline:
    global _instance
    if _instance is None:
        _instance = TestDesignPipeline(temperature=temperature)
    return _instance


def reset_pipeline() -> None:
    global _instance
    _instance = None
    logger.info("[TEST DESIGN] Singleton reset")
