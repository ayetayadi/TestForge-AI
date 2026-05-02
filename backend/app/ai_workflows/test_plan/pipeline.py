"""
ISTQB §5.1.1 Test Plan Generation Pipeline.

3 steps — no agent loop, one LLM call:
  1. summarize_risks(risks)       → aggregate risk distribution, recommend test types
  2. LLM call                     → generate complete test plan draft
  3. build_plan_record(...)       → sanitize, compute PERT, assemble final dict
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langsmith import traceable
from pydantic import BaseModel, Field

from app.ai_workflows.test_plan.plan_builder import (
    summarize_risks,
    recommend_test_types,
    estimate_duration,
    build_plan_record,
)
from app.ai_workflows.test_plan.prompts import TEST_PLAN_PROMPT
from app.llm.llm_control import create_llm
from .config import LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


# ============================================================
# LLM OUTPUT SCHEMA
# ============================================================

class TestPlanDraft(BaseModel):
    title: str = Field(description="Short professional title including project name and scope")
    description: str = Field(description="2-3 sentences summarizing what this test plan covers")
    objective: str = Field(description="2-4 measurable testing objectives")
    in_scope: str = Field(description="Bullet list of what IS covered")
    out_of_scope: str = Field(description="Bullet list of what is NOT covered")
    test_types: List[str] = Field(description="Selected from: functional, regression, smoke, security, performance, e2e, api")
    test_levels: List[str] = Field(description="Selected from: component, integration, system, acceptance, e2e")
    environment: str = Field(description="One of: dev, staging, prod, uat")
    entry_criteria: str = Field(description="3-4 conditions required before testing starts")
    exit_criteria: str = Field(description="3-4 measurable conditions that mark testing as done")
    approach: str = Field(description="Testing strategy: risk-based prioritization, test types mix, automation intent")
    assumptions: str = Field(description="2-3 hypotheses the team relies on")
    constraints: str = Field(description="2-3 real constraints (timeline, resources, tools)")
    reasoning: str = Field(description="Brief explanation of main choices")
    stakeholders: str = Field(description="Roles: QA Engineer, Developer, PO, Tech Lead with responsibilities")
    communication: str = Field(description="Communication: daily standup, progress reports, channels")
    
# ============================================================
# PIPELINE
# ============================================================

class TestPlanPipeline:
    """
    ISTQB §5.1.1 — Génération du Plan de Test à partir des résultats d'analyse des risques.

    Step 1 — summarize_risks: distribution par niveau, top risques, types recommandés, PERT
    Step 2 — LLM: génère le brouillon complet du plan de test
    Step 3 — build_plan_record: sanitize, finalise le dict prêt pour persistance
    """

    def __init__(self, temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL):
        logger.info("[TEST PLAN] Initializing pipeline...")
        llm = create_llm(temperature=temperature, model=model, max_tokens=LLM_MAX_TOKENS)
        self._llm = llm.with_structured_output(TestPlanDraft)
        logger.info("[TEST PLAN] Ready")

    async def _emit(self, callback: Optional[Callable], event_type: str, data: dict) -> None:
        if callback is None:
            return
        try:
            await callback(event_type, data)
        except Exception:
            pass

    @traceable(name="test_plan_pipeline")
    async def run(
        self,
        project_name: str,
        project_key: str,
        project_id: str,
        risks: List[Dict[str, Any]],
        user_stories: List[Dict[str, Any]] = None,
        scope_type: str = "manual",
        scope_refs: List[str] = None,
        environment: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Args:
            project_name: display name of the Jira project
            project_key: Jira project key (e.g. "SCRUM")
            project_id: UUID of the JiraProject record (FK for TestPlan)
            risks: list of risk dicts from risk_analysis pipeline
            user_stories: list of story dicts with keys: issue_key, title, acceptance_criteria (optional)
            scope_type: epic | sprint | release | manual
            scope_refs: e.g. ["Sprint 4"] or ["SCRUM-12", "SCRUM-13"]
            environment: override — if None, LLM decides
        """
        user_stories = user_stories or []
        scope_refs = scope_refs or []

        logger.info(
            f"[TEST PLAN] Starting: project={project_key} "
            f"risks={len(risks)} stories={len(user_stories)} scope={scope_type}"
        )

        try:
            # ── STEP 1: SUMMARIZE RISKS ─────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "analyzing",
                "message": "Summarizing risk analysis results...",
            })

            risk_summary = summarize_risks(risks)
            stories_text = " ".join(
                f"{s.get('issue_key', '')} {s.get('title', '')}"
                + " ".join(s.get('acceptance_criteria', []))
                for s in user_stories
            )
            recommendations = recommend_test_types(risk_summary, stories_text)
            duration = estimate_duration(risk_summary, len(user_stories) or len(risks))

            # ── STEP 2: LLM GENERATES DRAFT ────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "generating",
                "message": "AI generating test plan draft (ISTQB §5.1.1)...",
            })

            try:
                result: TestPlanDraft = await asyncio.wait_for(
                    self._call_llm(
                        project_name=project_name,
                        project_key=project_key,
                        scope_type=scope_type,
                        scope_refs=scope_refs,
                        environment_hint=environment or "staging",
                        risk_summary=risk_summary,
                        duration=duration,
                        recommendations=recommendations,
                        user_stories=user_stories,
                    ),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(f"[TEST PLAN] LLM timed out after {LLM_TIMEOUT_SECONDS}s")
                raise RuntimeError("LLM call timed out")

            # ── STEP 3: BUILD RECORD ────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "finalizing",
                "message": "Finalizing test plan record...",
            })

            plan_record = build_plan_record(
                llm_output=result.model_dump(),
                risk_summary=risk_summary,
                duration=duration,
                project_id=project_id,
                scope_type=scope_type,
                scope_refs=scope_refs,
                environment_override=environment,
                user_stories=user_stories,
                recommendations=recommendations,
            )

            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": (
                    f"Test plan draft generated. "
                    f"PERT estimate: {duration['realistic']} working days. "
                    f"Status: AI_PROPOSED (awaiting tester validation)"
                ),
                "test_types": plan_record["test_types"],
                "test_levels": plan_record["test_levels"],
                "duration": duration,
            })

            self._log_summary(project_key, plan_record, risk_summary, duration)

            return {
                **plan_record,
                "workflow_status": "success",
                "recommendations": recommendations,
            }

        except Exception as exc:
            logger.error(f"[TEST PLAN] Fatal error: {exc}", exc_info=True)
            return {
                "project_id": project_id,
                "title": f"Test Plan — {project_name}",
                "description": "",
                "objective": "",
                "scope_type": scope_type,
                "scope_refs": scope_refs or [],
                "in_scope": "",
                "out_of_scope": "",
                "test_types": ["functional"],
                "test_levels": ["system"],
                "environment": environment or "staging",
                "entry_criteria": "",
                "exit_criteria": "",
                "approach": "",
                "assumptions": "",
                "constraints": "",
                "status": "draft",
                "workflow_status": "error",
                "error": str(exc),
            }

    async def _call_llm(
        self,
        project_name: str,
        project_key: str,
        scope_type: str,
        scope_refs: List[str],
        environment_hint: str,
        risk_summary: Dict[str, Any],
        duration: Dict[str, Any],
        recommendations: Dict[str, Any],
        user_stories: List[Dict[str, Any]],
    ) -> TestPlanDraft:
        counts = risk_summary["counts"]

        # Stories summary: max 15 lines to stay within token budget
        stories_lines = [
            f"  • [{s.get('issue_key', '?')}] {s.get('title', '')[:80]}"
            for s in user_stories[:15]
        ]
        if len(user_stories) > 15:
            stories_lines.append(f"  ... and {len(user_stories) - 15} more")
        stories_summary = "\n".join(stories_lines) or "  (none provided)"

        prompt = TEST_PLAN_PROMPT.format(
            project_name=project_name,
            project_key=project_key,
            scope_type=scope_type,
            scope_refs=", ".join(scope_refs) if scope_refs else "not specified",
            environment_hint=environment_hint,
            story_count=len(user_stories),
            sprint_count=len(scope_refs) if scope_type == "sprint" else 1,
            epic_count=len(scope_refs) if scope_type == "epic" else 1,   
            stories_summary=stories_summary,
            count_critical=counts.get("critical", 0),
            count_high=counts.get("high", 0),
            count_medium=counts.get("medium", 0),
            count_low=counts.get("low", 0),
            top_risks=risk_summary["risk_text"],
            duration_optimistic=duration["optimistic"],
            duration_realistic=duration["realistic"],
            duration_pessimistic=duration["pessimistic"],
            recommended_types=", ".join(recommendations["test_types"]),
            recommended_levels=", ".join(recommendations["test_levels"]),
        )
        return await self._llm.ainvoke(prompt)

    def _log_summary(
        self,
        project_key: str,
        plan: Dict[str, Any],
        risk_summary: Dict[str, Any],
        duration: Dict[str, Any],
    ) -> None:
        logger.info(
            f"[RESULT] project={project_key} "
            f"types={plan['test_types']} levels={plan['test_levels']} "
            f"env={plan['environment']} "
            f"PERT={duration['realistic']}d "
            f"risks={risk_summary['counts']}"
        )


# ============================================================
# SINGLETON
# ============================================================

_instance: Optional[TestPlanPipeline] = None


def get_pipeline(temperature: float = LLM_TEMPERATURE) -> TestPlanPipeline:
    global _instance
    if _instance is None:
        _instance = TestPlanPipeline(temperature=temperature)
    return _instance


def reset_pipeline() -> None:
    global _instance
    _instance = None
    logger.info("[TEST PLAN] Singleton reset")
