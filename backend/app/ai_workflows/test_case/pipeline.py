"""
ISTQB §5.4 Test Case Design Pipeline - Simplified for 1 US = 1 Risk.

2 metrics only:
  - AC Coverage per User Story (ISTQB §4.3.2)
  - Risk level determines test count (ISTQB §5.2.3)
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
    validate_ac_coverage,
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
# LLM OUTPUT SCHEMA (inchangé)
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
    tags: List[str]
    covered_ac_indices: List[int]
    reasoning: str
    covered_risk_ids: List[str] = Field(default_factory=list)  # Gardé pour traçabilité


class TestCaseBatch(BaseModel):
    test_cases: List[TestCaseOutput]


# ============================================================
# TYPE ORDER
# ============================================================
_TYPE_ORDER = {"positive": 0, "negative": 1, "boundary": 2}


# ============================================================
# PIPELINE SIMPLIFIÉ
# ============================================================

class TestCasePipeline:
    """
    ISTQB §5.4 — Génère des cas de test pour UNE User Story.
    
    Calcule UNIQUEMENT l'AC Coverage pour cette US.
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
        user_story_id: Optional[str] = None,
        issue_key: str = "?",
        tc_start_index: int = 1,
        progress_callback: Optional[Callable] = None,
        scenario_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Génère des TCs pour UNE User Story.
        
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
        level = risk_level.lower()
        
        # Déterminer le nombre de tests par type
        base_counts = RISK_LEVEL_TEST_COUNTS.get(
            level, 
            RISK_LEVEL_TEST_COUNTS.get("default", {"positive": 1, "negative": 1, "boundary": 0})
        )

        _ALL_TYPES = {"positive", "negative", "boundary"}
        if scenario_types and set(scenario_types) != _ALL_TYPES:
            # Partial selection: guarantee at least 1 TC for each chosen type,
            # regardless of what RISK_LEVEL_TEST_COUNTS says for this risk level.
            selected = set(scenario_types)
            counts = {
                "positive": 1 if "positive" in selected else 0,
                "negative": 1 if "negative" in selected else 0,
                "boundary": 1 if "boundary" in selected else 0,
            }
        else:
            # All 3 selected (or none specified): honour RISK_LEVEL_TEST_COUNTS.
            counts = {
                "positive": base_counts["positive"],
                "negative": base_counts["negative"],
                "boundary": base_counts["boundary"],
            }
        
        total_count = counts["positive"] + counts["negative"] + counts["boundary"]

        logger.info(
            f"[TEST CASE] Starting: issue={issue_key} risk={level} "
            f"total={total_count} ac={len(acceptance_criteria)}"
        )

        try:
            # ── STEP 1: ANALYZE CONTEXT ──────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "analyzing",
                "message": f"Preparing context: {total_count} test cases required (risk: {level})...",
            })

            # ── STEP 2: LLM GENERATION ────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "generating",
                "message": f"Generating {total_count} test cases...",
            })

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

            # ── STEP 3: VALIDATE & REPAIR ─────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "validating",
                "message": "Validating Gherkin and computing AC coverage...",
            })

            raw_tcs = self._repair_gherkin(raw_tcs)

            # 🔥 LA SEULE COUVERTURE CALCULÉE
            ac_coverage = validate_ac_coverage(raw_tcs, acceptance_criteria)

            if not ac_coverage["is_sufficient"]:
                logger.warning(
                    f"[TEST CASE] AC coverage {ac_coverage['coverage_pct']:.0%} — "
                    f"uncovered: {ac_coverage['uncovered'][:3]}"
                )

            # ── STEP 4: FINALIZE ─────────────────────────
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
                    f"Generated {tcs_generated} test cases. "
                    f"AC Coverage: {ac_coverage['coverage_pct']:.0%}"
                ),
                "count": tcs_generated,
                "ac_coverage": ac_coverage,
            })

            self._log_summary(issue_key, level, finalized, ac_coverage)

            return {
                "test_cases": finalized,
                "count": tcs_generated,
                "risk_level": level,
                "ac_coverage": ac_coverage,  # ← PLUS DE "coverage" wrapper
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
                "ac_coverage": empty_ac_coverage,
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
        ac_coverage: Dict[str, Any],
    ) -> None:
        type_counts: Dict[str, int] = {}
        for tc in test_cases:
            t = tc.get("test_type", "?")
            type_counts[t] = type_counts.get(t, 0) + 1

        logger.info(
            f"[RESULT] issue={issue_key} risk={risk_level} total={len(test_cases)} "
            f"types={type_counts} | AC={ac_coverage['coverage_pct']:.0%}"
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