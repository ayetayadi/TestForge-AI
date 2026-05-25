"""
ISTQB §5.4 Test Case Design Pipeline.

Flow per User Story:
  1. User picks ONE scenario type (positive | negative | boundary)
  2. count = ceil(total_ACs / AC_TO_TC_RATIO), minimum 1
  3. LLM generates {count} test cases of the chosen type
  4. AC coverage check (≥ 80%)
  5. If insufficient → correction loop (max MAX_CORRECTION_ITERATIONS)
"""

import asyncio
import logging
import math
from typing import Any, Callable, Dict, List, Optional

from langfuse import observe
from langfuse import get_client as get_langfuse_client
from langsmith import traceable
from pydantic import BaseModel, Field

from app.ai_workflows.test_case.test_case_builder import (
    validate_gherkin,
    parse_gherkin_steps,
    extract_postconditions,
    normalize_gherkin,
    build_tc_code,
)
from app.ai_workflows.test_case.coverage_checker import (
    validate_ac_coverage,
    suggest_hints,
)
from app.ai_workflows.test_case.prompts import (
    TEST_CASE_GENERATION_PROMPT,
    CORRECTION_PROMPT,
)
from app.llm.llm_control import create_llm
from .config import (
    LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS,
    AC_TO_TC_RATIO, MAX_CORRECTION_ITERATIONS,
)

logger = logging.getLogger(__name__)

VALID_SCENARIO_TYPES = {"positive", "negative", "boundary"}


# ============================================================
# LLM OUTPUT SCHEMA
# ============================================================

class StepOutput(BaseModel):
    order: int = Field(description="Step number starting at 1")
    action: str = Field(description="What the tester does (imperative)")
    expected: str = Field(description="Observable result after this action")


class TestCaseOutput(BaseModel):
    title: str = Field(description="Short imperative sentence, max 100 chars")
    test_type: str = Field(description="positive | negative | boundary")
    priority: str = Field(description="critical | high | medium | low")
    preconditions: List[str]
    postconditions: List[str]
    gherkin_scenario: str
    steps: List[StepOutput]
    test_data: Dict[str, Any]
    expected_results: List[str]
    covered_ac_indices: List[int]
    reasoning: str
    covered_risk_ids: List[str] = Field(default_factory=list)


class TestCaseBatch(BaseModel):
    test_cases: List[TestCaseOutput]


# ============================================================
# TYPE ORDER (for finalize sorting)
# ============================================================
_TYPE_ORDER = {"positive": 0, "negative": 1, "boundary": 2}


# ============================================================
# PIPELINE
# ============================================================

class TestCasePipeline:
    """ISTQB §5.4 — Generates test cases for ONE User Story."""

    def __init__(self, temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL):
        logger.info("[TEST CASE] Initializing pipeline...")
        llm = create_llm(temperature=temperature, model=model, max_tokens=LLM_MAX_TOKENS)
        self._llm = llm.with_structured_output(TestCaseBatch)
        logger.info("[TEST CASE] Ready")

    async def _emit(self, callback: Optional[Callable], event_type: str, data: dict) -> None:
        if callback is None:
            return
        try:
            await callback(event_type, data)
        except Exception:
            pass

    @observe(name="test_case_pipeline")
    @traceable(name="test_case_pipeline")
    async def run(
        self,
        story: str,
        acceptance_criteria: List[str] = None,
        risk_level: str = "medium",
        risk_score: float = 1.5,
        risk_description: str = "",
        risk_mitigation: str = "",
        risk_ids: List[str] = None,
        user_story_id: Optional[str] = None,
        issue_key: str = "?",
        tc_start_index: int = 1,
        progress_callback: Optional[Callable] = None,
        scenario_type: str = "positive",
    ) -> Dict[str, Any]:
        """
        Generate TCs for ONE User Story.

        Returns:
            {
                "test_cases": [...],
                "count": int,
                "risk_level": str,
                "ac_coverage": {...},
                "coverage_hints": [...],
                "feature_gherkin": str,
                "user_story_id": str,
                "issue_key": str,
                "workflow_status": str
            }
        """
        acceptance_criteria = acceptance_criteria or []
        risk_ids = risk_ids or []

        # Normalise scenario type
        scenario_type = scenario_type.lower() if scenario_type else "positive"
        if scenario_type not in VALID_SCENARIO_TYPES:
            logger.warning(f"[TEST CASE] Unknown scenario_type '{scenario_type}', defaulting to 'positive'")
            scenario_type = "positive"

        level = risk_level.lower()

        # STEP 2: Estimate count = ceil(total_ACs / ratio), minimum 1
        count = max(1, math.ceil(len(acceptance_criteria) / AC_TO_TC_RATIO)) if acceptance_criteria else 1

        logger.info(
            f"[TEST CASE] Starting: issue={issue_key} type={scenario_type} "
            f"count={count} ac={len(acceptance_criteria)}"
        )

        try:
            # ── STEP 1: ANALYZE CONTEXT ──────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "analyzing",
                "message": (
                    f"Estimating {count} {scenario_type} test case(s) "
                    f"for {len(acceptance_criteria)} AC(s)..."
                ),
            })

            risk_label_map: Dict[str, str] = {
                f"RISK-{i + 1}": rid for i, rid in enumerate(risk_ids)
            }

            # ── STEP 3-4: INITIAL LLM GENERATION ─────────
            await self._emit(progress_callback, "phase", {
                "phase": "generating",
                "message": f"Generating {count} {scenario_type} test case(s)...",
            })

            try:
                batch: TestCaseBatch = await asyncio.wait_for(
                    self._call_llm(
                        story, acceptance_criteria, level, risk_score,
                        risk_description, risk_mitigation, risk_ids, scenario_type, count,
                    ),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(f"[TEST CASE] LLM timed out after {LLM_TIMEOUT_SECONDS}s")
                raise RuntimeError("LLM call timed out")

            if batch is None:
                raise RuntimeError("LLM returned None — structured output parsing failed (no tool call in response)")
            raw_tcs = [tc.model_dump() for tc in batch.test_cases]
            self._remap_risk_ids(raw_tcs, risk_label_map)

            # ── STEP 5: VALIDATE & REPAIR ─────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "validating",
                "message": "Validating Gherkin and computing AC coverage...",
            })

            raw_tcs = self._repair_gherkin(raw_tcs)
            ac_coverage = validate_ac_coverage(raw_tcs, acceptance_criteria)

            # ── STEP 6: CORRECTION LOOP ───────────────────
            iteration = 0
            while not ac_coverage["is_sufficient"] and iteration < MAX_CORRECTION_ITERATIONS:
                iteration += 1
                uncovered = ac_coverage["uncovered"]
                correction_count = max(1, math.ceil(len(uncovered) / AC_TO_TC_RATIO))

                logger.info(
                    f"[TEST CASE] Coverage {ac_coverage['coverage_pct']:.0%} < 80% "
                    f"— correction {iteration}/{MAX_CORRECTION_ITERATIONS}: "
                    f"{len(uncovered)} uncovered AC(s), generating {correction_count} more TC(s)"
                )

                await self._emit(progress_callback, "phase", {
                    "phase": "correcting",
                    "message": (
                        f"Coverage {ac_coverage['coverage_pct']:.0%} — "
                        f"correction {iteration}: generating {correction_count} more TC(s)..."
                    ),
                })

                try:
                    extra_batch: TestCaseBatch = await asyncio.wait_for(
                        self._call_llm_correction(
                            story, acceptance_criteria, uncovered,
                            level, risk_mitigation, risk_description, risk_ids, scenario_type, correction_count,
                        ),
                        timeout=LLM_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[TEST CASE] Correction LLM timed out at iteration {iteration}")
                    break

                extra_tcs = [tc.model_dump() for tc in extra_batch.test_cases]
                self._remap_risk_ids(extra_tcs, risk_label_map)
                extra_tcs = self._repair_gherkin(extra_tcs)
                raw_tcs.extend(extra_tcs)
                ac_coverage = validate_ac_coverage(raw_tcs, acceptance_criteria)

            # ── STEP 7: FINALIZE ─────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "finalizing",
                "message": "Assigning TC codes and building feature Gherkin...",
            })

            finalized = self._finalize(raw_tcs, user_story_id, tc_start_index)
            tcs_generated = len(finalized)
            feature_gherkin = self._build_feature_gherkin(story, finalized)

            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": (
                    f"Generated {tcs_generated} {scenario_type} test case(s). "
                    f"AC Coverage: {ac_coverage['coverage_pct']:.0%}"
                ),
                "count": tcs_generated,
                "ac_coverage": ac_coverage,
            })

            self._log_summary(issue_key, level, scenario_type, finalized, ac_coverage)

            # Fire DeepEval quality score in background (non-blocking)
            if finalized:
                from app.core.observability import fire_evaluation, is_deepeval_configured
                if is_deepeval_configured():
                    eval_input = f"User Story: {story}\n\nAcceptance Criteria:\n" + "\n".join(
                        f"- {ac}" for ac in acceptance_criteria
                    )
                    eval_output = feature_gherkin or "\n\n".join(
                        tc.get("gherkin_scenario", "") for tc in finalized
                    )
                    trace_id = None
                    try:
                        lf = get_langfuse_client()
                        trace_id = lf.get_current_trace_id()
                        lf.update_current_span(
                            input={"story": story, "ac_count": len(acceptance_criteria)},
                            output={"tc_count": tcs_generated, "coverage": ac_coverage.get("coverage_pct", 0)},
                            metadata={"scenario_type": scenario_type, "issue_key": issue_key},
                        )
                    except Exception:
                        pass
                    asyncio.create_task(fire_evaluation("test_case_quality", eval_input, eval_output, trace_id))

            return {
                "test_cases": finalized,
                "count": tcs_generated,
                "risk_level": level,
                "scenario_type": scenario_type,
                "ac_coverage": ac_coverage,
                "coverage_hints": suggest_hints(ac_coverage["uncovered"]),
                "feature_gherkin": feature_gherkin,
                "issue_key": issue_key,
                "user_story_id": user_story_id,
                "workflow_status": "success",
            }

        except Exception as exc:
            logger.error(f"[TEST CASE] Fatal error: {exc}", exc_info=True)
            empty_ac_coverage = {
                "is_sufficient": False,
                "coverage_pct": 0.0,
                "covered_count": 0,
                "total_count": len(acceptance_criteria),
                "uncovered": acceptance_criteria,
                "uncovered_indices": list(range(len(acceptance_criteria))),
            }
            return {
                "test_cases": [],
                "count": 0,
                "risk_level": level,
                "scenario_type": scenario_type,
                "ac_coverage": empty_ac_coverage,
                "coverage_hints": [],
                "feature_gherkin": "",
                "issue_key": issue_key,
                "user_story_id": user_story_id,
                "workflow_status": "error",
                "error": str(exc),
            }

    # ============================================================
    # LLM CALLS
    # ============================================================

    async def _call_llm(
        self,
        story: str,
        acceptance_criteria: List[str],
        risk_level: str,
        risk_score: float,
        risk_description: str,
        risk_mitigation: str,
        risk_ids: List[str],
        scenario_type: str,
        count: int,
    ) -> TestCaseBatch:
        ac_text = (
            "\n".join(f"{i}. {ac}" for i, ac in enumerate(acceptance_criteria))
            if acceptance_criteria else "(none)"
        )
        risk_ids_list = (
            "\n".join(f"  - RISK-{i + 1}" for i in range(len(risk_ids)))
            if risk_ids else "  (no accepted risks linked to this user story — use empty list [])"
        )
        prompt = TEST_CASE_GENERATION_PROMPT.format(
            story=story,
            acceptance_criteria=ac_text,
            risk_level=risk_level.upper(),
            risk_score=risk_score,
            risk_description=risk_description or "N/A",
            risk_mitigation=risk_mitigation or "N/A",
            risk_ids_list=risk_ids_list,
            scenario_type=scenario_type,
            count=count,
        )
        return await self._llm.ainvoke(prompt)

    async def _call_llm_correction(
        self,
        story: str,
        acceptance_criteria: List[str],
        uncovered_acs: List[str],
        risk_level: str,
        risk_mitigation: str,
        risk_description: str,
        risk_ids: List[str],
        scenario_type: str,
        count: int,
    ) -> TestCaseBatch:
        ac_text = (
            "\n".join(f"{i}. {ac}" for i, ac in enumerate(acceptance_criteria))
            if acceptance_criteria else "(none)"
        )
        uncovered_text = "\n".join(f"- {ac}" for ac in uncovered_acs)
        risk_ids_list = (
            "\n".join(f"  - RISK-{i + 1}" for i in range(len(risk_ids)))
            if risk_ids else "  (no accepted risks — use empty list [])"
        )
        prompt = CORRECTION_PROMPT.format(
            story=story,
            acceptance_criteria=ac_text,
            uncovered_acs=uncovered_text,
            risk_level=risk_level.upper(),
            risk_ids_list=risk_ids_list,
            scenario_type=scenario_type,
            count=count,
        )
        return await self._llm.ainvoke(prompt)

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def _remap_risk_ids(test_cases: List[Dict[str, Any]], risk_label_map: Dict[str, str]) -> None:
        if not risk_label_map:
            return
        for tc in test_cases:
            tc["covered_risk_ids"] = [
                risk_label_map[label]
                for label in tc.get("covered_risk_ids", [])
                if label in risk_label_map
            ]

    def _repair_gherkin(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        repaired = []
        for tc in test_cases:
            gherkin = tc.get("gherkin_scenario", "")

            if gherkin:
                gherkin = normalize_gherkin(gherkin)
                tc["gherkin_scenario"] = gherkin

            is_valid, issues = validate_gherkin(gherkin)
            if not is_valid:
                logger.warning(
                    f"[TEST CASE] Gherkin issues in '{tc.get('title', '?')}': {issues}"
                )

            if not tc.get("steps") and gherkin:
                parsed = parse_gherkin_steps(gherkin)
                tc["steps"] = [
                    {"order": s["order"], "action": s["action"], "expected": s["expected"]}
                    for s in parsed
                ]

            if not tc.get("postconditions") and gherkin:
                tc["postconditions"] = extract_postconditions(gherkin)

            repaired.append(tc)
        return repaired

    def _finalize(
        self,
        test_cases: List[Dict[str, Any]],
        user_story_id: Optional[str],
        start_index: int,
    ) -> List[Dict[str, Any]]:
        sorted_tcs = sorted(
            test_cases, key=lambda tc: _TYPE_ORDER.get(tc.get("test_type", ""), 99)
        )

        finalized = []
        for order, tc in enumerate(sorted_tcs, start=1):
            steps = [
                {
                    "order": s.get("order", order),
                    "action": s.get("action", ""),
                    "expected": s.get("expected", ""),
                }
                for s in tc.get("steps", [])
                if isinstance(s, dict)
            ]

            finalized.append({
                "tc_code": build_tc_code(start_index + order - 1),
                "title": tc.get("title", ""),
                "test_type": tc.get("test_type", "positive"),
                "priority": tc.get("priority", "medium"),
                "preconditions": tc.get("preconditions", []),
                "postconditions": tc.get("postconditions", []),
                "gherkin_source": tc.get("gherkin_scenario", ""),
                "steps": steps,
                "test_data": tc.get("test_data") or {},
                "expected_results": tc.get("expected_results", []),
                "user_story_id": user_story_id,
                "test_suite_id": None,
                "execution_order": order,
                "is_active": True,
                "_covered_ac_indices": tc.get("covered_ac_indices", []),
                "_reasoning": tc.get("reasoning", ""),
                "risk_ids": tc.get("covered_risk_ids", []),
            })

        return finalized

    def _build_feature_gherkin(self, story: str, test_cases: List[Dict[str, Any]]) -> str:
        title = story.strip().splitlines()[0][:120] if story.strip() else "User Story"
        lines = [f"Feature: {title}", ""]
        for tc in test_cases:
            gherkin = tc.get("gherkin_source", "").strip()
            if gherkin:
                lines.append(gherkin)
                lines.append("")
        return "\n".join(lines)

    def _log_summary(
        self,
        issue_key: str,
        risk_level: str,
        scenario_type: str,
        test_cases: List[Dict[str, Any]],
        ac_coverage: Dict[str, Any],
    ) -> None:
        logger.info(
            f"[RESULT] issue={issue_key} risk={risk_level} type={scenario_type} "
            f"total={len(test_cases)} | AC={ac_coverage['coverage_pct']:.0%}"
        )


# ============================================================
# SINGLETON
# ============================================================

_instances: dict[str, TestCasePipeline] = {}


def get_pipeline(temperature: float = LLM_TEMPERATURE) -> TestCasePipeline:
    from app.llm.llm_control import get_worker_api_key
    api_key = get_worker_api_key() or "default"
    if api_key not in _instances:
        logger.info(f"[TEST CASE] Creating pipeline instance for key: {api_key[:12]}...")
        _instances[api_key] = TestCasePipeline(temperature=temperature)
    return _instances[api_key]


def reset_pipeline() -> None:
    _instances.clear()
    logger.info("[TEST CASE] All pipeline instances reset")
