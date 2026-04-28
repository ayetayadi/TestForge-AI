"""
Test Suite Organization Pipeline.

3 steps — no agent loop, one optional LLM call (for naming only):
  1. group(test_cases, strategy)  → divide test cases into logical groups
  2. LLM call                     → generate professional titles and descriptions
  3. finalize(suites)             → assign execution_order, build records
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langsmith import traceable
from pydantic import BaseModel, Field

from app.ai_workflows.test_suite.suite_organizer import (
    group_by_risk_level,
    group_by_test_type,
    group_by_feature,
    group_mixed,
    assign_suite_order,
    build_suite_record,
)
from app.ai_workflows.test_suite.prompts import TEST_SUITE_NAMING_PROMPT
from app.llm.llm_control import create_llm
from .config import (
    LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS,
    GROUPING_STRATEGY,
)

logger = logging.getLogger(__name__)


# ============================================================
# LLM OUTPUT SCHEMA
# ============================================================

class SuiteNameOutput(BaseModel):
    group_key: str = Field(description="The group key this name applies to")
    title: str = Field(description="Professional suite title, max 80 chars")
    description: str = Field(description="1-2 sentences describing the suite purpose")
    suite_type: str = Field(description="feature | epic | sprint | smoke | regression | negative | security | performance | e2e")
    priority: str = Field(description="critical | high | medium | low")


class SuiteNamingBatch(BaseModel):
    suites: List[SuiteNameOutput] = Field(description="One entry per group")


# ============================================================
# STRATEGY DISPATCHER
# ============================================================

_STRATEGY_MAP = {
    "risk_level": group_by_risk_level,
    "test_type":  group_by_test_type,
    "feature":    group_by_feature,
    "mixed":      group_mixed,
}


# ============================================================
# PIPELINE
# ============================================================

class TestSuitePipeline:
    """
    Organizes generated test cases into TestSuite records.

    Step 1 — group: divide test cases using the chosen strategy
    Step 2 — LLM: generate professional suite titles and descriptions
    Step 3 — finalize: assign execution_order, build TestSuite-ready dicts
    """

    def __init__(self, temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL):
        logger.info("[TEST SUITE] Initializing pipeline...")
        llm = create_llm(temperature=temperature, model=model, max_tokens=LLM_MAX_TOKENS)
        self._llm = llm.with_structured_output(SuiteNamingBatch)
        logger.info("[TEST SUITE] Ready")

    async def _emit(self, callback: Optional[Callable], event_type: str, data: dict) -> None:
        if callback is None:
            return
        try:
            await callback(event_type, data)
        except Exception:
            pass

    @traceable(name="test_suite_pipeline")
    async def run(
        self,
        test_cases: List[Dict[str, Any]],
        test_plan_id: str,
        project_name: str = "",
        strategy: str = GROUPING_STRATEGY,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Args:
            test_cases: list of finalized test case dicts from TestCasePipeline
                        (must have: tc_code, test_type, priority, tags,
                         _risk_level, _epic, _component — injected upstream)
            test_plan_id: UUID of the parent TestPlan
            project_name: used in suite titles
            strategy: risk_level | test_type | feature | mixed
        """
        logger.info(
            f"[TEST SUITE] Starting: plan={test_plan_id} "
            f"tc_count={len(test_cases)} strategy={strategy}"
        )

        if not test_cases:
            return {
                "suites": [],
                "count": 0,
                "strategy": strategy,
                "workflow_status": "success",
                "note": "No test cases provided",
            }

        try:
            # ── STEP 1: GROUP ────────────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "grouping",
                "message": f"Grouping {len(test_cases)} test cases by strategy '{strategy}'...",
            })

            group_fn = _STRATEGY_MAP.get(strategy, group_by_risk_level)
            groups: Dict[str, List[Dict[str, Any]]] = group_fn(test_cases)

            logger.info(f"[TEST SUITE] Groups: {[(k, len(v)) for k, v in groups.items()]}")

            # ── STEP 2: LLM NAMING ──────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "naming",
                "message": f"Generating titles for {len(groups)} suites...",
            })

            try:
                naming: SuiteNamingBatch = await asyncio.wait_for(
                    self._call_llm(groups, project_name, strategy),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
                names_by_key = {n.group_key: n for n in naming.suites}
            except Exception as e:
                logger.warning(f"[TEST SUITE] LLM naming failed, using defaults: {e}")
                names_by_key = {}

            # ── STEP 3: FINALIZE ────────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "finalizing",
                "message": "Assigning execution order to suites...",
            })

            raw_suites = []
            for group_key, tcs in groups.items():
                name_info = names_by_key.get(group_key)
                record = build_suite_record(
                    group_key=group_key,
                    test_cases=tcs,
                    test_plan_id=test_plan_id,
                    title=name_info.title if name_info else "",
                    description=name_info.description if name_info else "",
                    suite_type=name_info.suite_type if name_info else None,
                    priority=name_info.priority if name_info else None,
                )
                raw_suites.append(record)

            ordered_suites = assign_suite_order(raw_suites)

            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": f"Created {len(ordered_suites)} test suites.",
                "count": len(ordered_suites),
                "suites": [
                    {"title": s["title"], "tc_count": s["_tc_count"], "order": s["execution_order"]}
                    for s in ordered_suites
                ],
            })

            self._log_summary(test_plan_id, ordered_suites)

            return {
                "suites": ordered_suites,
                "count": len(ordered_suites),
                "strategy": strategy,
                "workflow_status": "success",
            }

        except Exception as exc:
            logger.error(f"[TEST SUITE] Fatal error: {exc}", exc_info=True)
            return {
                "suites": [],
                "count": 0,
                "strategy": strategy,
                "workflow_status": "error",
                "error": str(exc),
            }

    async def _call_llm(
        self,
        groups: Dict[str, List[Dict[str, Any]]],
        project_name: str,
        strategy: str,
    ) -> SuiteNamingBatch:
        groups_text_lines = []
        for key, tcs in groups.items():
            sample_titles = [tc.get("title", "")[:60] for tc in tcs[:3]]
            groups_text_lines.append(
                f'- group_key: "{key}" | {len(tcs)} test cases\n'
                f'  Sample tests: {"; ".join(sample_titles)}'
            )
        groups_text = "\n".join(groups_text_lines)

        prompt = TEST_SUITE_NAMING_PROMPT.format(
            project_name=project_name or "Project",
            strategy=strategy,
            suite_groups=groups_text,
        )
        return await self._llm.ainvoke(prompt)

    def _log_summary(self, test_plan_id: str, suites: List[Dict[str, Any]]) -> None:
        for s in suites:
            logger.info(
                f"[RESULT] plan={test_plan_id} suite='{s['title']}' "
                f"type={s['suite_type']} order={s['execution_order']} "
                f"tc_count={s['_tc_count']}"
            )


# ============================================================
# SINGLETON
# ============================================================

_instance: Optional[TestSuitePipeline] = None


def get_pipeline(temperature: float = LLM_TEMPERATURE) -> TestSuitePipeline:
    global _instance
    if _instance is None:
        _instance = TestSuitePipeline(temperature=temperature)
    return _instance


def reset_pipeline() -> None:
    global _instance
    _instance = None
    logger.info("[TEST SUITE] Singleton reset")
