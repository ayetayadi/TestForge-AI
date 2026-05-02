"""
ISTQB §5.4 Test Case Design Pipeline.

4 steps — one LLM call per user story:
  1. analyze_context   → compute required counts, build prompt
  2. LLM call          → generate full test cases (preconditions, postconditions,
                         steps, test_data, expected_results, gherkin)
  3. validate_and_repair → validate Gherkin structure, compute all 3 coverages
  4. finalize          → assign tc_codes, build feature-level gherkin, sort by type
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

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
    validate_explicit_coverage,
    compute_risk_coverage,
    compute_requirements_coverage,
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
    test_type: str = Field(description="positive | negative | boundary")
    priority: str = Field(description="critical | high | medium | low")
    preconditions: List[str] = Field(description="System state required BEFORE the test starts")
    postconditions: List[str] = Field(description="Verifiable system state AFTER the test completes")
    gherkin_scenario: str = Field(description="Full Gherkin BDD scenario with ALL possible scenarios (Scenario / Scenario Outline)")
    steps: List[StepOutput] = Field(description="Structured steps mirroring the Gherkin scenario")
    test_data: Dict[str, Any] = Field(description="Concrete fictional values used in this test")
    expected_results: List[str] = Field(description="Final assertions — what must be TRUE when the test passes")
    tags: List[str] = Field(description="2-4 classification tags")
    covered_ac_indices: List[int] = Field(description="0-based indices of covered acceptance criteria")
    reasoning: str = Field(description="One sentence: which behavior this verifies and why it matters")
    covered_risk_ids: List[str] = Field(default_factory=list)

class TestCaseBatch(BaseModel):
    test_cases: List[TestCaseOutput] = Field(description="All generated test cases")


# ============================================================
# TYPE ORDER FOR SORTING (positive → negative → boundary)
# ============================================================
_TYPE_ORDER = {"positive": 0, "negative": 1, "boundary": 2}


# ============================================================
# PIPELINE
# ============================================================

class TestCasePipeline:
    """
    ISTQB §5.4 — Generates structured test cases from a User Story.

    Each test case includes: preconditions, postconditions, steps, test_data,
    expected_results, and a Gherkin BDD scenario with all possible scenarios.

    Returns three coverage metrics:
      - AC Coverage          = (ACs with >= 1 TC / Total ACs) x 100
      - Risk Coverage        = (Risks with >= 1 TC / Total accepted risks) x 100
      - Requirements Coverage = (USs with >= 1 TC / Total USs) x 100
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
        risk_level: str = "medium",
        risk_score: float = 1.5,
        risk_description: str = "",
        risk_ids: List[str] = None,
        total_accepted_risks: int = 0,
        user_story_id: Optional[str] = None,
        total_user_stories: int = 1,
        covered_user_stories_before: int = 0,
        issue_key: str = "?",
        tc_start_index: int = 1,
        progress_callback: Optional[Callable] = None,
        scenario_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Args:
            story:                       User story text.
            acceptance_criteria:         List of AC strings for this user story.
            risk_level:                  Risk level key (critical/high/medium/low).
            risk_score:                  Numeric risk score.
            risk_description:            Human-readable risk description.
            risk_ids:                    IDs of accepted risks linked to this user story.
            total_accepted_risks:        Total accepted risks in the project scope (for Risk Coverage denominator).
            user_story_id:               DB ID of this user story.
            total_user_stories:          Total user stories in the project scope (for Requirements Coverage denominator).
            covered_user_stories_before: Number of user stories already covered before this run (for aggregation).
            issue_key:                   Jira/issue key for logging.
            tc_start_index:              Starting index for TC code numbering.
            progress_callback:           Optional async callback(event_type, data).
            scenario_types:              List of scenario types to generate.
        """
        acceptance_criteria = acceptance_criteria or []
        risk_ids = risk_ids or []
        level = risk_level.lower()
        base_counts = RISK_LEVEL_TEST_COUNTS.get(level, RISK_LEVEL_TEST_COUNTS.get("default", {"positive": 1, "negative": 1, "boundary": 0}))

        if scenario_types:
            counts = {}
            if "positive" in scenario_types:
                counts["positive"] = base_counts["positive"]
            else:
                counts["positive"] = 0
            
            if "negative" in scenario_types:
                counts["negative"] = base_counts["negative"]
            else:
                counts["negative"] = 0
            
            if "boundary" in scenario_types:
                counts["boundary"] = base_counts["boundary"]
            else:
                counts["boundary"] = 0
        else:
            # Comportement par défaut : tous les types
            counts = {
                "positive": base_counts["positive"],
                "negative": base_counts["negative"],
                "boundary": base_counts["boundary"],
            }
        
        total_count = counts["positive"] + counts["negative"] + counts["boundary"]


        logger.info(
            f"[TEST CASE] Starting: issue={issue_key} risk={level} "
            f"total={total_count} ac={len(acceptance_criteria)} risks={len(risk_ids)}"
        )

        try:
            # ── STEP 1: ANALYZE CONTEXT ─────────────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "analyzing",
                "message": f"Preparing context: {total_count} test cases required (risk: {level})...",
            })

            # ── STEP 2: LLM GENERATION ──────────────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "generating",
                "message": f"Generating {total_count} test cases with full Gherkin scenarios...",
            })

            # Build RISK-N label ↔ UUID mapping so the LLM can reference short IDs
            risk_label_map: Dict[str, str] = {
                f"RISK-{i + 1}": rid for i, rid in enumerate(risk_ids)
            }

            try:
                batch: TestCaseBatch = await asyncio.wait_for(
                    self._call_llm(
                        story, acceptance_criteria, level, risk_score,
                        risk_description, counts, total_count, risk_ids,
                    ),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(f"[TEST CASE] LLM timed out after {LLM_TIMEOUT_SECONDS}s")
                raise RuntimeError("LLM call timed out")

            raw_tcs = [tc.model_dump() for tc in batch.test_cases]

            # Map RISK-N labels back to actual UUIDs
            if risk_label_map:
                for tc in raw_tcs:
                    tc["covered_risk_ids"] = [
                        risk_label_map[label]
                        for label in tc.get("covered_risk_ids", [])
                        if label in risk_label_map
                    ]

            # ── STEP 3: VALIDATE & REPAIR ───────────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "validating",
                "message": "Validating Gherkin structure and computing coverage metrics...",
            })

            raw_tcs = self._repair_gherkin(raw_tcs)

            ac_coverage = validate_explicit_coverage(raw_tcs, acceptance_criteria)

            if not ac_coverage["is_sufficient"]:
                logger.warning(
                    f"[TEST CASE] AC coverage {ac_coverage['coverage_pct']:.0%} — "
                    f"uncovered: {ac_coverage['uncovered'][:3]}"
                )

            # ── STEP 4: FINALIZE ────────────────────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "finalizing",
                "message": "Assigning TC codes and building feature Gherkin...",
            })

            finalized = self._finalize(raw_tcs, user_story_id, tc_start_index)

            tcs_generated = len(finalized)

            risk_cov = compute_risk_coverage(
                test_cases=raw_tcs,
                total_accepted_risks=total_accepted_risks,
                accepted_risk_ids=risk_ids,
            )

            covered_us = covered_user_stories_before + (1 if tcs_generated > 0 else 0)
            req_cov = compute_requirements_coverage(
                covered_us_count=covered_us,
                total_user_stories=total_user_stories,
            )

            feature_gherkin = self._build_feature_gherkin(story, finalized)

            coverage_summary = {
                "ac_coverage": ac_coverage,
                "risk_coverage": risk_cov,
                "requirements_coverage": req_cov,
            }

            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": (
                    f"Generated {tcs_generated} test cases. "
                    f"AC: {ac_coverage['coverage_pct']:.0%} | "
                    f"Risk: {risk_cov['coverage_pct']:.0%} | "
                    f"Requirements: {req_cov['coverage_pct']:.0%}"
                ),
                "count": tcs_generated,
                "coverage": coverage_summary,
            })

            self._log_summary(issue_key, level, finalized, coverage_summary)

            return {
                "test_cases": finalized,
                "count": tcs_generated,
                "risk_level": level,
                "coverage": coverage_summary,
                "coverage_hints": suggest_hints(ac_coverage["uncovered"]),
                "feature_gherkin": feature_gherkin,
                "issue_key": issue_key,
                "user_story_id": user_story_id,
                "workflow_status": "success",
            }

        except Exception as exc:
            logger.error(f"[TEST CASE] Fatal error: {exc}", exc_info=True)
            empty_coverage = {
                "ac_coverage": {
                    "is_sufficient": False, "coverage_pct": 0.0,
                    "covered_count": 0, "total_count": len(acceptance_criteria),
                    "uncovered": acceptance_criteria, "uncovered_indices": list(range(len(acceptance_criteria))),
                },
                "risk_coverage": {
                    "coverage_pct": 0.0, "covered_count": 0,
                    "total_count": total_accepted_risks, "covered_risk_ids": [],
                    "is_sufficient": False,
                },
                "requirements_coverage": {
                    "coverage_pct": covered_user_stories_before / total_user_stories if total_user_stories else 0.0,
                    "covered_count": covered_user_stories_before,
                    "total_count": total_user_stories,
                    "is_sufficient": False,
                },
            }
            return {
                "test_cases": [],
                "count": 0,
                "risk_level": level,
                "coverage": empty_coverage,
                "coverage_hints": [],
                "feature_gherkin": "",
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
        risk_ids: List[str] = None,
    ) -> TestCaseBatch:
        ac_text = (
            "\n".join(f"{i}. {ac}" for i, ac in enumerate(acceptance_criteria))
            if acceptance_criteria else "(none)"
        )
        risk_ids = risk_ids or []
        risk_ids_list = (
            "\n".join(f"  - RISK-{i + 1}" for i in range(len(risk_ids)))
            if risk_ids else "  (no accepted risks linked to this user story — use empty list [])"
        )
        try:
            prompt = TEST_CASE_GENERATION_PROMPT.format(
                story=story,
                acceptance_criteria=ac_text,
                risk_level=risk_level.upper(),
                risk_score=risk_score,
                risk_description=risk_description or "N/A",
                risk_ids_list=risk_ids_list,
                count_positive=counts["positive"],
                count_negative=counts["negative"],
                count_boundary=counts["boundary"],
                total_count=total_count,
            )
        except KeyError as e:
            logger.error(f"[TEST CASE] Missing prompt key: {e}")
            raise

        return await self._llm.ainvoke(prompt)

    def _repair_gherkin(self, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        For each test case:
          - Normalize Gherkin indentation and keyword casing
          - Parse steps from Gherkin if steps list is empty
          - Extract postconditions from Then/And clauses if empty
          - Log a warning for structurally invalid Gherkin
        """
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
                "tags": tc.get("tags", []),
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
        """
        Consolidate all test case Gherkin scenarios into a single Feature block.
        """
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
        test_cases: List[Dict[str, Any]],
        coverage: Dict[str, Any],
    ) -> None:
        type_counts: Dict[str, int] = {}
        for tc in test_cases:
            t = tc.get("test_type", "?")
            type_counts[t] = type_counts.get(t, 0) + 1

        ac_pct = coverage["ac_coverage"]["coverage_pct"]
        risk_pct = coverage["risk_coverage"]["coverage_pct"]
        req_pct = coverage["requirements_coverage"]["coverage_pct"]

        logger.info(
            f"[RESULT] issue={issue_key} risk={risk_level} total={len(test_cases)} "
            f"types={type_counts} | "
            f"AC={ac_pct:.0%} Risk={risk_pct:.0%} Req={req_pct:.0%}"
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
