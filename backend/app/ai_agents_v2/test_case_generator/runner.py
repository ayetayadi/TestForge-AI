"""Entry point for the TestCaseGenerator agent."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from langchain_core.messages import HumanMessage

from app.ai_agents_v2.test_case_generator.graph import compiled_test_case_graph
from app.ai_agents_v2.test_case_generator.state import TestCaseAgentState
from app.ai_agents_v2.test_case_generator.gherkin import enrich_with_gherkin

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tc_gen")


def _compute_quality_score(test_cases: List[Dict]) -> Tuple[int, Dict]:
    if not test_cases:
        return 0, {
            "score": 0,
            "issues": ["No test cases were generated"],
            "fix_instructions": "Re-run with a clearer user story and acceptance criteria.",
            "type_coverage": "None",
        }

    n = len(test_cases)
    issues: List[str] = []
    score = 0

    raw_types = {(tc.get("test_type") or "Positive").strip() for tc in test_cases}
    type_coverage = ", ".join(sorted(raw_types))
    lower_types = {t.lower() for t in raw_types}

    has_positive = any(t == "positive" for t in lower_types)
    has_negative = any(t == "negative" for t in lower_types)
    has_edge     = any(t in ("boundary value", "edge case", "equivalence partitioning") for t in lower_types)
    has_smoke    = any(t == "smoke" for t in lower_types)

    if has_positive: score += 10
    if has_negative: score += 12
    else:            issues.append("No Negative test cases — failure paths not covered")
    if has_edge:     score += 6
    else:            issues.append("No Boundary/Edge test cases — boundary conditions not tested")
    if has_smoke:    score += 2

    step_counts = [len(tc.get("steps") or []) for tc in test_cases]
    no_steps_n  = sum(1 for s in step_counts if s == 0)
    avg_steps   = sum(step_counts) / n

    if no_steps_n:
        issues.append(f"{no_steps_n} test case(s) have no steps")

    if avg_steps >= 5:   score += 30
    elif avg_steps >= 4: score += 24
    elif avg_steps >= 3: score += 18
    elif avg_steps >= 2: score += 10
    elif avg_steps >= 1: score += 5

    no_desc_n = sum(1 for tc in test_cases if not (tc.get("description") or "").strip())
    no_tags_n = sum(1 for tc in test_cases if not (tc.get("tags") or []))

    if no_desc_n == 0:       score += 15
    elif no_desc_n <= n // 3: score += 8
    else: issues.append(f"{no_desc_n} test case(s) are missing descriptions")

    if no_tags_n == 0:       score += 10
    elif no_tags_n <= n // 3: score += 5
    else: issues.append(f"{no_tags_n} test case(s) have no tags")

    if n >= 10:   score += 15
    elif n >= 7:  score += 10
    elif n >= 5:  score += 6
    elif n >= 3:  score += 3
    else: issues.append(f"Only {n} test case(s) — consider broader coverage")

    score = max(0, min(100, score))
    fix_instructions = (
        "Suggestions: " + "; ".join(issues[:3]) + "."
        if issues else "Test cases are comprehensive and well-structured."
    )

    return score, {
        "score": score,
        "issues": issues,
        "fix_instructions": fix_instructions,
        "type_coverage": type_coverage,
    }


def _normalize_test_case(raw: Any, index: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {
            "id": f"TC-{index + 1:03d}",
            "name": str(raw),
            "description": "",
            "priority": "Medium",
            "test_type": "Positive",
            "tags": [],
            "steps": [],
        }
    steps_raw = raw.get("steps") or []
    steps = []
    for s in steps_raw:
        if isinstance(s, dict):
            steps.append({
                "step_number": int(s.get("step_number", len(steps) + 1)),
                "description": str(s.get("description", "")),
                "expected_result": str(s.get("expected_result", "")),
            })
    return {
        "id":          raw.get("id")          or f"TC-{index + 1:03d}",
        "name":        raw.get("name")        or f"Test Case {index + 1}",
        "description": raw.get("description") or "",
        "priority":    raw.get("priority")    or "Medium",
        "test_type":   raw.get("test_type")   or "Positive",
        "tags":        raw.get("tags")        or [],
        "steps":       steps,
    }


async def _precompute_analysis(
    user_story: str,
    acceptance_criteria: List[str],
) -> Dict[str, Any]:
    """
    Run story analysis in Python (no LLM call) before the agent graph starts.
    This eliminates the analyze_story LLM round-trip entirely.
    """
    from app.ai_agents_v2.test_case_generator.tools import _extract_feature_areas
    feature_areas = _extract_feature_areas(user_story, acceptance_criteria)

    try:
        from app.ai_workflows.user_story_refinement.evaluators import score_story
        from app.ai_workflows.user_story_refinement.utils.text_processing import (
            detect_language,
            extract_actor_from_story,
        )
        actor    = extract_actor_from_story(user_story) or "unspecified"
        language = detect_language(user_story)
        scored   = await score_story(user_story, acceptance_criteria)
        return {
            "actor":              actor,
            "language":           language,
            "feature_areas":      feature_areas,
            "ac_count":           len(acceptance_criteria),
            "acceptance_criteria": acceptance_criteria,
            "testability_score":  round(scored.get("testability_score", 0), 2),
            "is_testable":        scored.get("is_testable", True),
            "quality_issues":     scored.get("issues", [])[:6],
            "suggestions":        scored.get("suggestions", [])[:4],
            "final_score":        round(scored.get("final_score", 0), 2),
        }
    except Exception as exc:
        logger.warning("[test_case_generator] Pre-analysis fallback: %s", exc)
        return {
            "actor": "user", "language": "en", "feature_areas": feature_areas,
            "ac_count": len(acceptance_criteria), "acceptance_criteria": acceptance_criteria,
            "testability_score": 0.6, "is_testable": True,
            "quality_issues": [], "suggestions": [], "final_score": 0.6,
        }


async def run_test_case_agent(
    user_story: str,
    acceptance_criteria: List[str],
    model: str = "openai/gpt-4o-mini",
) -> Dict[str, Any]:
    """
    Run the TestCaseGenerator agent and return structured results.
    """
    # Pre-compute analysis before the LLM loop — saves one full API round-trip
    analysis_result = await _precompute_analysis(user_story, acceptance_criteria)

    ac_text = "\n".join(f"- {ac}" for ac in acceptance_criteria)
    initial_message = HumanMessage(content=(
        f"User Story:\n{user_story}\n\n"
        f"Acceptance Criteria:\n{ac_text}\n\n"
        "Story analysis is already done (see CURRENT PROGRESS). "
        "Call draft_test_cases with comprehensive test cases covering all ACs. "
        "Do NOT call save_test_cases — saving is automatic after draft/refine."
    ))

    initial_state: TestCaseAgentState = {
        "messages":              [initial_message],
        "user_story":            user_story,
        "acceptance_criteria":   acceptance_criteria,
        "model":                 model,
        "analysis_result":       analysis_result,   # pre-loaded — skip analyze_story call
        "test_cases_structured": None,
        "user_story_analysis":   None,
        "critique_result":       None,
        "iteration_count":       0,
        "approved":              False,
        "flagged_for_human":     False,
        "saved_paths":           None,
        "thought_action_log":    [],
    }

    logger.info(
        "[test_case_generator] Starting | story=%s… | ACs=%d | model=%s",
        user_story[:60], len(acceptance_criteria), model,
    )

    loop = asyncio.get_running_loop()
    final_state: TestCaseAgentState = await loop.run_in_executor(
        _EXECUTOR,
        compiled_test_case_graph.invoke,
        initial_state,
    )

    # Count refinement rounds from message history (iteration_count in state may be stale)
    messages = final_state.get("messages") or []
    refine_rounds = sum(
        1
        for msg in messages
        for tc in (getattr(msg, "tool_calls", None) or [])
        if tc.get("name") == "refine_test_cases"
    )

    logger.info(
        "[test_case_generator] Finished | approved=%s | flagged=%s | refine_rounds=%d",
        final_state.get("approved"),
        final_state.get("flagged_for_human"),
        refine_rounds,
    )

    raw_cases  = final_state.get("test_cases_structured") or []
    test_cases = [_normalize_test_case(tc, i) for i, tc in enumerate(raw_cases)]
    quality_score, quality_review = _compute_quality_score(test_cases)

    # Single focused LLM call: add Gherkin scenario + test data to each test case.
    # Runs after quality is finalized — does not affect the test case generation loop.
    test_cases = await enrich_with_gherkin(test_cases, user_story, model)

    return {
        "approved":            final_state.get("approved", False),
        "flagged_for_human":   final_state.get("flagged_for_human", False),
        "user_story_analysis": final_state.get("user_story_analysis"),
        "analysis_result":     final_state.get("analysis_result"),
        "critique_result":     final_state.get("critique_result"),
        "refine_rounds":       refine_rounds,
        "last_critic_score":   quality_score,
        "last_critic_review":  quality_review,
        "thought_action_log":  final_state.get("thought_action_log", []),
        "test_cases":          test_cases,
    }
