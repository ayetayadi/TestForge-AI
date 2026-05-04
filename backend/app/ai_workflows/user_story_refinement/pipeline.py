"""
Simple LLM pipeline for User Story Refinement.

Workflow (4 fixed steps — no agent loop):
  1. score_story(original)        → identify issues & scores
  2. LLM call                     → fix specific issues found
  3. validate_constraints(...)    → safety / constraint check
  4. score_story(improved)        → measure final quality
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langsmith import traceable
from pydantic import BaseModel, Field

from app.ai_workflows.user_story_refinement.evaluators import (
    extract_acceptance_criteria,
    score_story,
    validate_constraints,
)
from app.ai_workflows.user_story_refinement.utils.text_processing import (
    clean_story_text,
    compare_similarity,
    extract_actor_from_story,
    verify_language_consistency,
    verify_role_preserved,
)
from app.llm.llm_control import create_llm
from app.ai_workflows.user_story_refinement.prompts import IMPROVEMENT_PROMPT
from .config import LLM_TEMPERATURE, MIN_SCORE_THRESHOLD, LLM_MODEL, LLM_MAX_TOKENS

logger = logging.getLogger(__name__)


# ============================================================
# LLM OUTPUT SCHEMA
# ============================================================

class ImprovementResult(BaseModel):
    improved_story: str = Field(description="The improved user story text")
    acceptance_criteria: List[str] = Field(description="Improved acceptance criteria list")
    reasoning: str = Field(description="What issues were found and what was changed")


# ============================================================
# PIPELINE
# ============================================================

class UserStoryRefinementPipeline:
    """
    Simple 4-step LLM pipeline for user story refinement.

    Step 1 — score original to identify issues
    Step 2 — LLM fixes specific issues (one call, structured output)
    Step 3 — validate constraints (language, role, similarity)
    Step 4 — score improved to measure progress
    """

    def __init__(self, temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL):
        logger.info("[PIPELINE] Initializing...")
        llm = create_llm(temperature=temperature, model=model, max_tokens=LLM_MAX_TOKENS)
        self._llm = llm.with_structured_output(ImprovementResult)
        logger.info("[PIPELINE] Ready")

    async def _emit(self, callback: Optional[Callable], event_type: str, data: dict) -> None:
        if callback is None:
            return
        try:
            await callback(event_type, data)
        except Exception:
            pass

    @traceable(name="user_story_refinement_pipeline")
    async def run(
        self,
        story: str,
        acceptance_criteria: List[str] = None,
        language: str = "en",
        jira_id: str = "?",
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        acceptance_criteria = acceptance_criteria or []
        original_actor = extract_actor_from_story(story)
        clean_story = clean_story_text(story)
    
        logger.info(f"[PIPELINE] Starting: jira_id={jira_id}")
    
        try:
            # ── PHASE 1: ANALYZING ──────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "analyzing", 
                "message": "🔍 Analyzing story quality..."
            })
            
            extracted = await extract_acceptance_criteria(clean_story, acceptance_criteria)
            ac = extracted.get("acceptance_criteria") or acceptance_criteria
            initial = await score_story(clean_story, ac)
    
            if initial.get("is_garbage"):
                await self._emit(progress_callback, "phase", {
                    "phase": "done", 
                    "message": "Story is too low quality to improve (garbage input)"
                })
                return self._build_result(
                    story=clean_story, ac=ac,
                    initial=initial, final=initial,
                    similarity=1.0, iterations=0, status="garbage_input",
                    jira_id=jira_id, original_actor=original_actor,
                )
    
            if initial.get("is_testable") and initial.get("final_score", 0) >= MIN_SCORE_THRESHOLD:
                logger.info("[PIPELINE] Already meets threshold — skipping improvement")
                await self._emit(progress_callback, "phase", {
                    "phase": "done", 
                    "message": "Story already meets quality threshold — no improvement needed"
                })
                return self._build_result(
                    story=clean_story, ac=ac,
                    initial=initial, final=initial,
                    similarity=1.0, iterations=0, status="success",
                    jira_id=jira_id, original_actor=original_actor,
                )
    
            # ── PHASE 2: IMPROVING ──────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "improving", 
                "message": "✨ Improving story with AI (this may take a moment)..."
            })
            
            try:
                improvement = await asyncio.wait_for(
                    self._call_llm(clean_story, ac, initial),
                    timeout=60,
                )
            except asyncio.TimeoutError:
                logger.error("[PIPELINE] LLM call timed out after 60s")
                raise RuntimeError("LLM call timed out")
            improved_story = improvement.improved_story or clean_story
            improved_ac = improvement.acceptance_criteria or ac
    
            # ── PHASE 3: FINALIZING ──────────────────────────────
            await self._emit(progress_callback, "phase", {
                "phase": "finalizing", 
                "message": "✓ Validating and calculating final score..."
            })
            
            validation = await validate_constraints(clean_story, improved_story, improved_ac)
    
            if not validation.get("is_safe"):
                logger.warning(f"[PIPELINE] Constraint violation — reverting: {validation.get('violations')}")
                await self._emit(progress_callback, "phase", {
                    "phase": "done",
                    "message": "Constraint violation — reverting to original",
                    "violations": validation.get("violations", []),
                })
                return self._build_result(
                    story=clean_story, ac=ac,
                    initial=initial, final=initial,
                    similarity=1.0, iterations=1, status="safe_revert",
                    violations=validation.get("violations", []),
                    reasoning=improvement.reasoning,
                    jira_id=jira_id, original_actor=original_actor,
                )
    
            final, similarity = await asyncio.gather(
                score_story(improved_story, improved_ac),
                compare_similarity(clean_story, improved_story),
            )

            if final.get("final_score", 0) < initial.get("final_score", 0):
                logger.warning(
                    f"[PIPELINE] Score regression {initial['final_score']:.3f} → {final['final_score']:.3f} — reverting"
                )
                return self._build_result(
                    story=clean_story, ac=ac,
                    initial=initial, final=initial,
                    similarity=1.0, iterations=1, status="safe_revert",
                    reasoning=improvement.reasoning,
                    jira_id=jira_id, original_actor=original_actor,
                )

            status = (
                "success"
                if final.get("is_testable") and final.get("final_score", 0) >= MIN_SCORE_THRESHOLD
                else "best_effort"
            )
    
            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": "✅ Story refinement complete!",
                "score": final.get("final_score", 0),
                "similarity": round(similarity, 3),
            })
    
            result = self._build_result(
                story=improved_story, ac=improved_ac,
                initial=initial, final=final,
                similarity=similarity, iterations=1, status=status,
                reasoning=improvement.reasoning,
                jira_id=jira_id, original_actor=original_actor,
                original_story=clean_story,
            )
            self._log_summary(result)
            return result
    
        except Exception as exc:
            logger.error(f"[PIPELINE] Fatal error: {exc}", exc_info=True)
            return {
                "improved_story": story,
                "acceptance_criteria": acceptance_criteria,
                "is_improved": False,
                "valid": False,
                "initial_score": 0.0,
                "final_score": 0.0,
                "score": 0.0,
                "testability_score": 0.0,
                "is_testable": False,
                "testability_issues": [],
                "similarity": 1.0,
                "language_consistent": False,
                "role_preserved": False,
                "original_actor": original_actor or "",
                "improved_actor": "",
                "iterations": 0,
                "workflow_status": "error",
                "stop_reason": "error",
                "violations": [],
                "thought_log": [],
                "jira_id": jira_id,
                "error": str(exc),
            }
    
    async def _call_llm(
        self,
        story: str,
        ac: List[str],
        score_result: Dict[str, Any],
    ) -> ImprovementResult:
        prompt = IMPROVEMENT_PROMPT.format(
            story=story,
            acceptance_criteria="\n".join(f"- {a}" for a in ac) if ac else "(none)",
            ac_count=len(ac),
            issues="\n".join(f"- {i}" for i in score_result.get("issues", [])) or "(none)",
            suggestions="\n".join(f"- {s}" for s in score_result.get("suggestions", [])) or "(none)",
            threshold=MIN_SCORE_THRESHOLD,
        )
        return await self._llm.ainvoke(prompt)

    def _build_result(
        self,
        story: str,
        ac: List[str],
        initial: Dict[str, Any],
        final: Dict[str, Any],
        similarity: float,
        iterations: int,
        status: str,
        jira_id: str,
        original_actor: str = "",
        original_story: str = None,
        violations: List[str] = None,
        reasoning: str = "",
    ) -> Dict[str, Any]:
        original_story = original_story or story
        violations = violations or []
        language_consistent = verify_language_consistency(original_story, story)
        role_preserved = verify_role_preserved(original_story, story)
        improved_actor = extract_actor_from_story(story)
        is_valid = language_consistent and not violations
        is_improved = story != original_story and is_valid

        return {
            "improved_story": story,
            "acceptance_criteria": ac,
            "is_improved": is_improved,
            "valid": is_valid,
            "initial_score": round(initial.get("final_score", 0.0), 3),
            "final_score": round(final.get("final_score", 0.0), 3),
            "score": round(final.get("final_score", 0.0), 3),
            "testability_score": round(final.get("testability_score", 0.0), 3),
            "is_testable": final.get("is_testable", False),
            "testability_issues": final.get("testability_issues", []),
            "similarity": round(similarity, 3),
            "language_consistent": language_consistent,
            "role_preserved": role_preserved,
            "original_actor": original_actor or "",
            "improved_actor": improved_actor or "",
            "iterations": iterations,
            "workflow_status": status,
            "stop_reason": status,
            "violations": violations,
            "thought_log": [reasoning] if reasoning else [],
            "jira_id": jira_id,
        }

    def _log_summary(self, result: Dict[str, Any]) -> None:
        delta = result["final_score"] - result["initial_score"]
        logger.info(
            f"[RESULT] jira={result['jira_id']} "
            f"score {result['initial_score']:.3f} → {result['final_score']:.3f} ({delta:+.3f}) "
            f"testability={result['testability_score']:.3f} "
            f"status={result['workflow_status']} iter={result['iterations']}"
        )


# ============================================================
# SINGLETON
# ============================================================

_instances: dict[str, UserStoryRefinementPipeline] = {}


def get_pipeline(temperature: float = LLM_TEMPERATURE) -> UserStoryRefinementPipeline:
    from app.llm.llm_control import get_worker_api_key
    api_key = get_worker_api_key() or "default"
    if api_key not in _instances:
        logger.info(f"[US REFINEMENT] Creating pipeline instance for key: {api_key[:12]}...")
        _instances[api_key] = UserStoryRefinementPipeline(temperature=temperature)
    return _instances[api_key]


def reset_pipeline() -> None:
    _instances.clear()
    logger.info("[US REFINEMENT] All pipeline instances reset")
