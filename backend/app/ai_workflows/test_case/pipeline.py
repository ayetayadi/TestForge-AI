"""
ISTQB §5.4 Test Case Design Pipeline — Gherkin BDD.

4 steps — no agent loop, one LLM call per user story:
  1. analyze_context(story, ac, risk)  → compute required counts, extract scenario hints
  2. LLM call                          → generate full Gherkin test cases with all fields
  3. validate_and_repair(tcs, ac)      → check Gherkin structure, compute AC coverage
  4. finalize(tcs)                     → assign tc_codes, parse postconditions, set order
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langsmith import traceable
from pydantic import BaseModel, Field

from app.ai_workflows.test_case.gherkin_generator import (
    validate_gherkin,
    parse_gherkin_steps,
    extract_postconditions,
    normalize_gherkin,
    build_tc_code,
)
from app.ai_workflows.test_case.coverage_checker import (
    validate_explicit_coverage,
    suggest_hints,
)
from app.ai_workflows.test_case.prompts import TEST_CASE_GENERATION_PROMPT
from app.llm.llm_control import create_llm
from .config import (
    LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS,
    RISK_LEVEL_TEST_COUNTS,
)

logger = logging.getLogger(__name__)


# ============================================================
# LLM OUTPUT SCHEMA
# ============================================================

class StepOutput(BaseModel):
    order: int = Field(description="Step number starting at 1")
    action: str = Field(description="What the tester does (imperative)")
    expected: str = Field(description="Observable result after this action (empty string for Given/When steps)")


class TestCaseOutput(BaseModel):
    title: str = Field(description="Short imperative sentence, max 100 chars")
    test_type: str = Field(description="positive | negative | edge_case")
    priority: str = Field(description="critical | high | medium | low")
    preconditions: List[str] = Field(description="State required BEFORE the test starts")
    postconditions: List[str] = Field(description="Observable state AFTER test completes, including cleanup")
    gherkin_scenario: str = Field(description="Full Gherkin BDD scenario (Scenario: / Given / When / Then)")
    steps: List[StepOutput] = Field(description="Structured steps matching the Gherkin scenario")
    test_data: Dict[str, Any] = Field(description="Concrete fictional values used in this test")
    expected_results: List[str] = Field(description="Final assertions — what must be TRUE when test passes")
    tags: List[str] = Field(description="2-4 classification tags")
    covered_ac_indices: List[int] = Field(description="0-based indices of covered acceptance criteria")
    reasoning: str = Field(description="Which behavior this verifies and why")


class TestCaseBatch(BaseModel):
    test_cases: List[TestCaseOutput] = Field(description="All generated test cases")


# ============================================================
# TYPE ORDER FOR SORTING (positive → negative → edge_case)
# ============================================================
_TYPE_ORDER = {"positive": 0, "negative": 1, "edge_case": 2}


# ============================================================
# PIPELINE
# ============================================================

class TestCasePipeline:
    """
    ISTQB §5.4 — Génère des cas de test Gherkin BDD à partir d'une User Story.

    Step 1 — analyze_context: determine required counts from risk level
    Step 2 — LLM: generate test cases with ALL fields (Gherkin, steps, preconditions,
                  postconditions, test_data, expected_results, coverage indices)
    Step 3 — validate_and_repair: validate Gherkin structure, compute AC coverage
    Step 4 — finalize: assign tc_codes, parse gherkin if steps empty, sort by type
    """

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

    @traceable(name="test_case_pipeline")
    async def run(
        self,
        story: str,
        acceptance_criteria: List[str] = None,
        risk_level: str = "moyenne",
        risk_score: float = 1.5,
        risk_description: str = "",
        user_story_id: Optional[str] = None,
        issue_key: str = "?",
        tc_start_index: int = 1,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        acceptance_criteria = acceptance_criteria or []
        level = risk_level.lower()
        counts = RISK_LEVEL_TEST_COUNTS.get(level, RISK_LEVEL_TEST_COUNTS["default"])
        total_count = counts["positive"] + counts["negative"] + counts["edge_case"]

        logger.info(
            f"[TEST CASE] Starting: issue={issue_key} risk={level} "
            f"total={total_count} ac={len(acceptance_criteria)}"
        )

        try:
            # ── STEP 1: ANALYZE CONTEXT ─────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "analyzing",
                "message": f"Preparing context: {total_count} test cases required (risk: {level})...",
            })

            # ── STEP 2: LLM GENERATION ──────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "generating",
                "message": f"Generating {total_count} Gherkin BDD test cases...",
            })

            try:
                batch: TestCaseBatch = await asyncio.wait_for(
                    self._call_llm(story, acceptance_criteria, level, risk_score, risk_description, counts, total_count),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(f"[TEST CASE] LLM timed out after {LLM_TIMEOUT_SECONDS}s")
                raise RuntimeError("LLM call timed out")

            raw_tcs = [tc.model_dump() for tc in batch.test_cases]

            # ── STEP 3: VALIDATE ────────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "validating",
                "message": "Validating Gherkin structure and AC coverage...",
            })

            raw_tcs = self._repair_gherkin(raw_tcs)
            coverage = validate_explicit_coverage(raw_tcs, acceptance_criteria)

            if not coverage["is_sufficient"]:
                logger.warning(
                    f"[TEST CASE] Coverage {coverage['coverage_pct']:.0%} — "
                    f"uncovered: {coverage['uncovered'][:3]}"
                )

            # ── STEP 4: FINALIZE ────────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "finalizing",
                "message": "Assigning TC codes and ordering...",
            })

            finalized = self._finalize(raw_tcs, user_story_id, tc_start_index)

            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": (
                    f"Generated {len(finalized)} test cases. "
                    f"AC coverage: {coverage['coverage_pct']:.0%}"
                ),
                "count": len(finalized),
                "coverage_pct": coverage["coverage_pct"],
            })

            self._log_summary(issue_key, level, finalized, coverage)

            return {
                "test_cases": finalized,
                "count": len(finalized),
                "risk_level": level,
                "coverage": coverage,
                "coverage_hints": suggest_hints(coverage["uncovered"]),
                "issue_key": issue_key,
                "user_story_id": user_story_id,
                "workflow_status": "success",
            }

        except Exception as exc:
            logger.error(f"[TEST CASE] Fatal error: {exc}", exc_info=True)
            return {
                "test_cases": [],
                "count": 0,
                "risk_level": level,
                "coverage": {"is_sufficient": False, "coverage_pct": 0.0, "uncovered": acceptance_criteria},
                "coverage_hints": [],
                "issue_key": issue_key,
                "user_story_id": user_story_id,
                "workflow_status": "error",
                "error": str(exc),
            }

    async def _call_llm(
        self,
        story: str,
        acceptance_criteria: List[str],
        risk_level: str,
        risk_score: float,
        risk_description: str,
        counts: Dict[str, int],
        total_count: int,
    ) -> TestCaseBatch:
        ac_text = "\n".join(f"{i}. {ac}" for i, ac in enumerate(acceptance_criteria)) if acceptance_criteria else "(none)"
        prompt = TEST_CASE_GENERATION_PROMPT.format(
            story=story,
            acceptance_criteria=ac_text,
            risk_level=risk_level.upper(),
            risk_score=risk_score,
            risk_description=risk_description or "N/A",
            count_positive=counts["positive"],
            count_negative=counts["negative"],
            count_edge_case=counts["edge_case"],
            total_count=total_count,
        )
        return await self._llm.ainvoke(prompt)

    def _repair_gherkin(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        For each test case:
        - Normalize the Gherkin text
        - If steps list is empty, parse them from the Gherkin
        - If postconditions is empty, extract them from Gherkin Then clauses
        - Log a warning if Gherkin is structurally invalid
        """
        repaired = []
        for tc in test_cases:
            gherkin = tc.get("gherkin_scenario", "")

            # Normalize
            if gherkin:
                gherkin = normalize_gherkin(gherkin)
                tc["gherkin_scenario"] = gherkin

            # Validate
            is_valid, issues = validate_gherkin(gherkin)
            if not is_valid:
                logger.warning(f"[TEST CASE] Gherkin issues in '{tc.get('title', '?')}': {issues}")

            # Repair steps if empty
            if not tc.get("steps") and gherkin:
                parsed = parse_gherkin_steps(gherkin)
                tc["steps"] = [{"order": s["order"], "action": s["action"], "expected": s["expected"]} for s in parsed]

            # Repair postconditions if empty
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
        sorted_tcs = sorted(test_cases, key=lambda tc: _TYPE_ORDER.get(tc.get("test_type", ""), 99))

        finalized = []
        for order, tc in enumerate(sorted_tcs, start=1):
            steps = []
            for s in tc.get("steps", []):
                if isinstance(s, dict):
                    steps.append({
                        "order": s.get("order", order),
                        "action": s.get("action", ""),
                        "expected": s.get("expected", ""),
                    })

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
                "tags": tc.get("tags", []),
                "risk_ids": [],
                "user_story_id": user_story_id,
                "test_suite_id": None,          # set later by test_suite pipeline
                "execution_order": order,        # refined later by prioritization
                "is_active": True,
                "_covered_ac_indices": tc.get("covered_ac_indices", []),
                "_reasoning": tc.get("reasoning", ""),
            })

        return finalized

    def _log_summary(
        self,
        issue_key: str,
        risk_level: str,
        test_cases: List[Dict[str, Any]],
        coverage: Dict[str, Any],
    ) -> None:
        type_counts: Dict[str, int] = {}
        for tc in test_cases:
            t = tc.get("test_type", "?")
            type_counts[t] = type_counts.get(t, 0) + 1
        logger.info(
            f"[RESULT] issue={issue_key} risk={risk_level} "
            f"total={len(test_cases)} types={type_counts} "
            f"coverage={coverage['coverage_pct']:.0%}"
        )


# ============================================================
# SINGLETON
# ============================================================

_instance: Optional[TestCasePipeline] = None


def get_pipeline(temperature: float = LLM_TEMPERATURE) -> TestCasePipeline:
    global _instance
    if _instance is None:
        _instance = TestCasePipeline(temperature=temperature)
    return _instance


def reset_pipeline() -> None:
    global _instance
    _instance = None
    logger.info("[TEST CASE] Singleton reset")
