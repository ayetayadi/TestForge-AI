"""
ISTQB §5.4 Test Case Design Pipeline.

Flow per User Story:
  1. User picks ONE scenario type (positive | negative | boundary)
  2. LLM analyzes all ACs, groups those sharing the same flow, generates one TC per group
  3. AC coverage check (≥ 80%)
  4. If insufficient → correction loop (max MAX_CORRECTION_ITERATIONS)
"""

import asyncio
import logging
import math
from typing import Any, Callable, Dict, List, Literal, Optional

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
    BATCH_GENERATION_PROMPT,
)
from app.llm.llm_control import create_llm
from .config import (
    LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS,
    AC_TO_TC_RATIO, MAX_CORRECTION_ITERATIONS,
    BATCH_LLM_MAX_TOKENS, BATCH_LLM_TIMEOUT_SECONDS, BATCH_MAX_STORIES,
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
    outcome_type: Literal["success", "error"] = Field(
        description=(
            "'success' if the test expects a successful outcome (positive test), "
            "'error' if the test expects an error, rejection, or failure (negative test)"
        )
    )
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
    estimated_duration: Optional[int] = Field(
        default=None,
        description="Estimated execution time in minutes (e.g. 5 for a simple TC, 15 for a complex one)"
    )


class TestCaseBatch(BaseModel):
    test_cases: List[TestCaseOutput]


class UserStoryBatchItem(BaseModel):
    story_index: int = Field(description="0-based index matching the input story list")
    test_cases: List[TestCaseOutput]


class AllStoriesBatch(BaseModel):
    stories: List[UserStoryBatchItem]


# ============================================================
# TYPE ORDER (for finalize sorting)
# ============================================================
_TYPE_ORDER = {"positive": 0, "negative": 1, "boundary": 2}

# Phrases in a title that betray boundary-value content even when test_type = "positive"
_BOUNDARY_TITLE_SIGNALS = frozenset({
    "minimum length", "maximum length", "min length", "max length",
    "minimum password", "maximum password", "minimum username", "maximum username",
    "minimum email", "maximum email", "long email", "long password", "long username",
    "long name", "long string", "at minimum", "at maximum", "at limit",
    "boundary", "edge case", "limit value", "empty string", "null value",
    "zero value", "too long", "too short", "special character", "special char",
})

def _has_boundary_signals(tc: dict) -> bool:
    title_lower = tc.get("title", "").lower()
    return any(signal in title_lower for signal in _BOUNDARY_TITLE_SIGNALS)


_ERROR_RESULT_PATTERNS = ("error message", "is not created", "is not updated", "no session token")


def _has_negative_signals(tc: dict) -> bool:
    # Primary: outcome_type declared by the LLM
    if tc.get("outcome_type", "success") == "error":
        return True
    # Backup: catch cases where LLM set outcome_type="success" but expected_results betray the truth
    results_lower = " ".join(tc.get("expected_results", [])).lower()
    return any(p in results_lower for p in _ERROR_RESULT_PATTERNS)


# ============================================================
# PIPELINE
# ============================================================

class TestCasePipeline:
    """ISTQB §5.4 — Generates test cases for ONE User Story."""

    def __init__(self, temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL):
        logger.info("[TEST CASE] Initializing pipeline...")
        llm = create_llm(temperature=temperature, model=model, max_tokens=LLM_MAX_TOKENS)
        self._llm = llm.with_structured_output(TestCaseBatch, method="json_mode")
        batch_llm = create_llm(temperature=temperature, model=model, max_tokens=BATCH_LLM_MAX_TOKENS)
        self._batch_llm = batch_llm.with_structured_output(AllStoriesBatch, method="json_mode")
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

        logger.info(
            f"[TEST CASE] Starting: issue={issue_key} type={scenario_type} "
            f"ac={len(acceptance_criteria)}"
        )

        try:
            # ── STEP 1: ANALYZE CONTEXT ──────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "analyzing",
                "message": (
                    f"Generating {scenario_type} test cases "
                    f"for {len(acceptance_criteria)} AC(s)..."
                ),
            })

            risk_label_map: Dict[str, str] = {
                f"RISK-{i + 1}": rid for i, rid in enumerate(risk_ids)
            }

            # ── STEP 3-4: INITIAL LLM GENERATION ─────────
            await self._emit(progress_callback, "phase", {
                "phase": "generating",
                "message": f"Generating {scenario_type} test cases...",
            })

            try:
                batch: TestCaseBatch = await asyncio.wait_for(
                    self._call_llm(
                        story, acceptance_criteria, level, risk_score,
                        risk_description, risk_mitigation, risk_ids, scenario_type,
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

                existing_titles = [tc.get("title", "") for tc in raw_tcs if tc.get("title")]
                try:
                    extra_batch: TestCaseBatch = await asyncio.wait_for(
                        self._call_llm_correction(
                            story, acceptance_criteria, uncovered,
                            existing_titles,
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

            finalized = self._finalize(raw_tcs, user_story_id, tc_start_index, scenario_type)
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
    # BATCH GENERATION (multiple user stories → single LLM call)
    # ============================================================

    @observe(name="test_case_batch_pipeline")
    async def run_batch(
        self,
        stories_data: List[Dict[str, Any]],
        scenario_type: str = "positive",
        risk_level: str = "medium",
        risk_score: float = 1.5,
        risk_description: str = "",
        risk_ids: List[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate TCs for MULTIPLE User Stories in a single LLM call.

        stories_data items must contain:
            user_story_id, issue_key, story, acceptance_criteria,
            risk_mitigation (optional), user_story_title (optional)

        Returns a list of result dicts in the same format as run().
        Falls back to individual run() calls if the batch LLM call fails.
        """
        if not stories_data:
            return []

        risk_ids = risk_ids or []
        scenario_type = scenario_type.lower()
        if scenario_type not in VALID_SCENARIO_TYPES:
            scenario_type = "positive"

        logger.info(
            f"[TC BATCH] Starting: {len(stories_data)} stories, type={scenario_type}"
        )

        await self._emit(progress_callback, "phase", {
            "phase": "generating",
            "message": f"Generating {scenario_type} test cases for {len(stories_data)} user stories...",
        })

        stories_block = self._format_stories_block(stories_data)
        story_count = len(stories_data)

        prompt = BATCH_GENERATION_PROMPT.format(
            scenario_type=scenario_type,
            story_count=story_count,
            story_count_minus_1=story_count - 1,
            stories_block=stories_block,
        )

        try:
            all_batch: AllStoriesBatch = await asyncio.wait_for(
                self._batch_llm.ainvoke(prompt),
                timeout=BATCH_LLM_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                f"[TC BATCH] Batch LLM failed ({exc.__class__.__name__}: {exc}), "
                "falling back to individual generation."
            )
            return await self._run_individual_fallback(
                stories_data, scenario_type, risk_level, risk_score,
                risk_description, risk_ids, progress_callback,
            )

        if all_batch is None:
            logger.warning("[TC BATCH] LLM returned None — falling back to individual generation.")
            return await self._run_individual_fallback(
                stories_data, scenario_type, risk_level, risk_score,
                risk_description, risk_ids, progress_callback,
            )

        story_items_by_index: Dict[int, UserStoryBatchItem] = {
            item.story_index: item for item in all_batch.stories
        }
        risk_label_map: Dict[str, str] = {
            f"RISK-{i + 1}": rid for i, rid in enumerate(risk_ids)
        }

        results: List[Dict[str, Any]] = []

        for idx, story_data in enumerate(stories_data):
            acceptance_criteria = story_data.get("acceptance_criteria", [])
            item = story_items_by_index.get(idx)

            if item is None or not item.test_cases:
                logger.warning(
                    f"[TC BATCH] No TCs in batch result for story {idx} "
                    f"({story_data.get('issue_key')}) — running correction."
                )
                raw_tcs: List[Dict[str, Any]] = []
            else:
                raw_tcs = [tc.model_dump() for tc in item.test_cases]
                self._remap_risk_ids(raw_tcs, risk_label_map)
                raw_tcs = self._repair_gherkin(raw_tcs)

            ac_coverage = validate_ac_coverage(raw_tcs, acceptance_criteria)

            if not ac_coverage["is_sufficient"]:
                uncovered = ac_coverage["uncovered"]
                correction_count = max(1, math.ceil(len(uncovered) / AC_TO_TC_RATIO))
                existing_titles = [tc.get("title", "") for tc in raw_tcs if tc.get("title")]
                logger.info(
                    f"[TC BATCH] Coverage {ac_coverage['coverage_pct']:.0%} for "
                    f"{story_data.get('issue_key')} — correcting with {correction_count} more TCs."
                )
                try:
                    extra_batch: TestCaseBatch = await asyncio.wait_for(
                        self._call_llm_correction(
                            story_data["story"], acceptance_criteria, uncovered,
                            existing_titles, risk_level,
                            story_data.get("risk_mitigation", "N/A"),
                            risk_description, risk_ids, scenario_type, correction_count,
                        ),
                        timeout=LLM_TIMEOUT_SECONDS,
                    )
                    extra_tcs = [tc.model_dump() for tc in extra_batch.test_cases]
                    self._remap_risk_ids(extra_tcs, risk_label_map)
                    extra_tcs = self._repair_gherkin(extra_tcs)
                    raw_tcs.extend(extra_tcs)
                    ac_coverage = validate_ac_coverage(raw_tcs, acceptance_criteria)
                except Exception as e:
                    logger.warning(
                        f"[TC BATCH] Correction failed for {story_data.get('issue_key')}: {e}"
                    )

            finalized = self._finalize(
                raw_tcs, story_data.get("user_story_id"), 1, scenario_type
            )
            feature_gherkin = self._build_feature_gherkin(story_data["story"], finalized)

            results.append({
                "test_cases": finalized,
                "count": len(finalized),
                "risk_level": risk_level,
                "scenario_type": scenario_type,
                "ac_coverage": ac_coverage,
                "coverage_hints": suggest_hints(ac_coverage["uncovered"]),
                "feature_gherkin": feature_gherkin,
                "issue_key": story_data.get("issue_key"),
                "user_story_id": story_data.get("user_story_id"),
                "workflow_status": "success",
            })

        logger.info(
            f"[TC BATCH] Done: {sum(r['count'] for r in results)} TCs "
            f"across {len(results)} stories."
        )
        return results

    async def _run_individual_fallback(
        self,
        stories_data: List[Dict[str, Any]],
        scenario_type: str,
        risk_level: str,
        risk_score: float,
        risk_description: str,
        risk_ids: List[str],
        progress_callback: Optional[Callable],
    ) -> List[Dict[str, Any]]:
        """Run individual pipeline.run() for each story when batch LLM fails."""
        tasks = [
            self.run(
                story=s["story"],
                acceptance_criteria=s.get("acceptance_criteria", []),
                risk_level=risk_level,
                risk_score=risk_score,
                risk_description=risk_description,
                risk_ids=risk_ids,
                user_story_id=s.get("user_story_id"),
                issue_key=s.get("issue_key", "?"),
                tc_start_index=1,
                progress_callback=progress_callback,
                scenario_type=scenario_type,
            )
            for s in stories_data
        ]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        for i, outcome in enumerate(outcomes):
            if isinstance(outcome, Exception):
                logger.error(
                    f"[TC BATCH FALLBACK] Failed for {stories_data[i].get('issue_key')}: {outcome}"
                )
                results.append({
                    "test_cases": [], "count": 0, "risk_level": risk_level,
                    "scenario_type": scenario_type,
                    "ac_coverage": {"is_sufficient": False, "coverage_pct": 0.0,
                                    "covered_count": 0, "total_count": 0,
                                    "uncovered": [], "uncovered_indices": []},
                    "coverage_hints": [], "feature_gherkin": "",
                    "issue_key": stories_data[i].get("issue_key"),
                    "user_story_id": stories_data[i].get("user_story_id"),
                    "workflow_status": "error", "error": str(outcome),
                })
            else:
                results.append(outcome)
        return results

    @staticmethod
    def _format_stories_block(stories_data: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for i, s in enumerate(stories_data):
            lines.append(f"[STORY {i}] {s.get('issue_key', '?')}")
            story_text = (s.get("story") or "").strip()
            lines.append(f"Story: {story_text[:400]}")
            acs = s.get("acceptance_criteria", [])
            if acs:
                lines.append("Acceptance Criteria:")
                for j, ac in enumerate(acs):
                    lines.append(f"  {j}. {ac}")
            else:
                lines.append("Acceptance Criteria: (none)")
            lines.append("")
        return "\n".join(lines)

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
        )
        return await self._llm.ainvoke(prompt)

    async def _call_llm_correction(
        self,
        story: str,
        acceptance_criteria: List[str],
        uncovered_acs: List[str],
        existing_titles: List[str],
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
        existing_titles_text = (
            "\n".join(f"  - {t}" for t in existing_titles)
            if existing_titles else "  (none yet)"
        )
        risk_ids_list = (
            "\n".join(f"  - RISK-{i + 1}" for i in range(len(risk_ids)))
            if risk_ids else "  (no accepted risks — use empty list [])"
        )
        prompt = CORRECTION_PROMPT.format(
            story=story,
            acceptance_criteria=ac_text,
            uncovered_acs=uncovered_text,
            existing_titles=existing_titles_text,
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
        scenario_type: str = "positive",
    ) -> List[Dict[str, Any]]:
        # Filter 1: keep only TCs matching the requested type field
        type_filtered = [
            tc for tc in test_cases
            if tc.get("test_type", "positive").lower().strip() == scenario_type
        ]
        if not type_filtered:
            logger.warning(
                f"[TEST CASE] No TCs matched type '{scenario_type}' "
                f"(got: {[tc.get('test_type') for tc in test_cases]}). Keeping all."
            )
            type_filtered = test_cases

        # Filter 2: reject boundary-content TCs when positive or negative was requested
        # (LLM sometimes sets test_type=positive but generates min/max/long/empty scenarios)
        if scenario_type != "boundary":
            content_ok = [tc for tc in type_filtered if not _has_boundary_signals(tc)]
            if content_ok:
                removed = len(type_filtered) - len(content_ok)
                if removed:
                    logger.warning(
                        f"[TEST CASE] Removed {removed} boundary-content TC(s) "
                        f"from '{scenario_type}' batch."
                    )
                type_filtered = content_ok

        # Filter 3: reject negative-content TCs when positive was requested
        # (LLM sometimes sets test_type=positive but generates invalid/reject/error scenarios)
        if scenario_type == "positive":
            content_ok = [tc for tc in type_filtered if not _has_negative_signals(tc)]
            if content_ok:
                removed = len(type_filtered) - len(content_ok)
                if removed:
                    logger.warning(
                        f"[TEST CASE] Removed {removed} negative-content TC(s) "
                        f"from 'positive' batch."
                    )
                type_filtered = content_ok

        # Deduplicate by normalized title (keeps first occurrence)
        seen_titles: set = set()
        deduped = []
        for tc in type_filtered:
            norm_title = tc.get("title", "").lower().strip()
            if norm_title in seen_titles:
                logger.warning(f"[TEST CASE] Duplicate title removed: '{tc.get('title')}'")
                continue
            seen_titles.add(norm_title)
            deduped.append(tc)

        # Sort: by type order first, then by coverage count descending (main TC first)
        sorted_tcs = sorted(
            deduped,
            key=lambda tc: (
                _TYPE_ORDER.get(tc.get("test_type", ""), 99),
                -len(tc.get("covered_ac_indices", [])),
            ),
        )

        # Ensure the TC with the most covered ACs is marked critical (main happy path)
        if scenario_type == "positive" and sorted_tcs:
            main_tc = sorted_tcs[0]
            if main_tc.get("priority", "medium") in ("low", "medium"):
                main_tc["priority"] = "critical"

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
                "outcome_type": tc.get("outcome_type", "success"),
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
                "estimated_duration": tc.get("estimated_duration"),
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
