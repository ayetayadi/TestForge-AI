"""
Test case generator tools.

Non-terminal (agent observes result and continues):
  analyze_story        — deep story analysis using existing evaluators
  draft_test_cases     — submit initial draft + get auto-critique immediately
  critique_test_cases  — explicit quality check (rarely needed; auto-critique is in draft/refine)
  refine_test_cases    — replace draft + get auto-critique immediately

Terminal (agent stops after calling):
  save_test_cases      — persist final result
  flag_human_review    — escalate ambiguous requirements
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field


# ── Shared schemas ─────────────────────────────────────────────────────────────

class TestCaseStepArg(BaseModel):
    step_number:     int = Field(description="Step number starting at 1")
    description:     str = Field(description="Atomic action the tester performs")
    expected_result: str = Field(description="Specific, verifiable outcome for this step")


class TestCaseArg(BaseModel):
    id:          str            = Field(description="Unique ID, e.g. TC-001")
    name:        str            = Field(description="Concise test case name (max 80 chars)")
    description: str            = Field(default="", description="One-sentence description")
    priority:    str            = Field(default="Medium", description="High | Medium | Low")
    test_type:   str            = Field(
        default="Positive",
        description="Positive | Negative | Boundary Value | Equivalence Partitioning | Edge Case | Smoke",
    )
    tags:        List[str]           = Field(default_factory=list, description="Lowercase tags")
    steps:       List[TestCaseStepArg] = Field(default_factory=list)


class UserStoryAnalysisArg(BaseModel):
    scope: str       = Field(default="", description="Concise scope description (1-2 sentences)")
    goals: List[str] = Field(default_factory=list, description="2-4 business goals")


# ── Feature area extraction ────────────────────────────────────────────────────

_FEATURE_MAP: Dict[str, List[str]] = {
    "authentication": ["login", "logout", "password", "auth", "token", "session", "signin"],
    "authorization":  ["permission", "role", "access", "forbidden", "restrict", "privilege"],
    "export":         ["export", "download", "csv", "pdf", "excel", "file", "squash"],
    "import":         ["import", "upload", "ingest", "sync"],
    "search":         ["search", "filter", "query", "find", "sort"],
    "crud":           ["create", "read", "update", "delete", "edit", "add", "remove", "modify"],
    "notification":   ["notify", "email", "alert", "message", "sms"],
    "validation":     ["validate", "verify", "check", "constraint", "format"],
    "api":            ["api", "endpoint", "rest", "http", "request", "response"],
    "ui":             ["display", "show", "render", "page", "button", "form", "interface"],
    "reporting":      ["report", "dashboard", "chart", "metric", "statistic", "analytics"],
    "mapping":        ["map", "mapping", "field", "transform", "convert"],
    "integration":    ["integration", "connect", "sync", "third-party", "external"],
}


def _extract_feature_areas(user_story: str, acceptance_criteria: List[str]) -> List[str]:
    combined = (user_story + " " + " ".join(acceptance_criteria)).lower()
    found = [area for area, kws in _FEATURE_MAP.items() if any(kw in combined for kw in kws)]
    return sorted(found) or ["general"]


# ── Shared critique logic — pure Python, zero LLM calls ───────────────────────

def _compute_critique(tcs: List[Dict], acceptance_criteria: List[str]) -> Dict[str, Any]:
    """Structural quality check. Called inside draft/refine/critique tools instantly."""
    issues: List[str]      = []
    suggestions: List[str] = []

    # 1. AC coverage heuristic
    uncovered_acs: List[str] = []
    for ac in acceptance_criteria:
        ac_words = {w.lower() for w in re.findall(r"\w+", ac) if len(w) > 3}
        if not ac_words:
            continue
        covered = any(
            bool(ac_words & set(re.findall(r"\w+",
                (tc.get("name", "") + " " + tc.get("description", "")).lower()
            )))
            for tc in tcs
        )
        if not covered:
            uncovered_acs.append(ac)
    if uncovered_acs:
        issues.append(f"ACs not clearly mapped to any test case: {uncovered_acs}")
        suggestions.append("Add dedicated test cases for each uncovered AC.")

    # 2. Test type diversity
    types_lower   = {tc.get("test_type", "Positive").lower() for tc in tcs}
    missing_types: List[str] = []
    if "negative" not in types_lower:
        missing_types.append("Negative")
        issues.append("No Negative test cases — invalid inputs and error paths untested.")
    if not any(t in types_lower for t in ("boundary value", "edge case", "equivalence partitioning")):
        missing_types.append("Boundary/Edge")
        issues.append("No Boundary Value or Edge Case tests — limit conditions untested.")
    if "smoke" not in types_lower:
        suggestions.append("Consider a Smoke test for the critical happy path.")

    # 3. Step quality
    no_steps  = [tc.get("id", "?") for tc in tcs if not tc.get("steps")]
    avg_steps = sum(len(tc.get("steps", [])) for tc in tcs) / len(tcs) if tcs else 0
    if no_steps:
        issues.append(f"Test cases with zero steps: {no_steps}")
    if 0 < avg_steps < 2:
        issues.append(f"Average {avg_steps:.1f} steps/test case is too shallow — aim for ≥3.")

    # 4. Count
    n = len(tcs)
    if n < 4:
        issues.append(f"Only {n} test cases — aim for at least {max(6, len(acceptance_criteria) * 2)}.")

    # 5. Descriptions
    no_desc = sum(1 for tc in tcs if not (tc.get("description") or "").strip())
    if no_desc > n // 2:
        issues.append(f"{no_desc}/{n} test cases missing descriptions.")

    quality_ok = len(issues) == 0
    return {
        "quality_ok":      quality_ok,
        "issue_count":     len(issues),
        "issues":          issues,
        "suggestions":     suggestions,
        "uncovered_acs":   uncovered_acs,
        "types_present":   sorted(types_lower),
        "missing_types":   missing_types,
        "avg_steps":       round(avg_steps, 1),
        "test_case_count": n,
        "verdict": (
            "GOOD — call save_test_cases."
            if quality_ok else
            "NEEDS IMPROVEMENT — call refine_test_cases to fix every issue above."
        ),
    }


# ── Tool 1: analyze_story ──────────────────────────────────────────────────────

class AnalyzeStoryInput(BaseModel):
    user_story:          str       = Field(description="The full user story text")
    acceptance_criteria: List[str] = Field(default_factory=list, description="List of ACs")


@tool("analyze_story", args_schema=AnalyzeStoryInput)
def analyze_story(user_story: str, acceptance_criteria: List[str]) -> str:
    """
    Analyze the user story using existing project evaluators.
    NOTE: analysis is usually pre-computed before the agent starts — check CURRENT PROGRESS
    before calling this. Only call if analysis_result is not yet available.
    Non-terminal.
    """
    feature_areas = _extract_feature_areas(user_story, acceptance_criteria)
    try:
        from app.ai_workflows.user_story_refinement.evaluators import score_story
        from app.ai_workflows.user_story_refinement.utils.text_processing import (
            detect_language, extract_actor_from_story,
        )
        actor    = extract_actor_from_story(user_story) or "unspecified"
        language = detect_language(user_story)
        loop = asyncio.new_event_loop()
        try:
            scored = loop.run_until_complete(score_story(user_story, acceptance_criteria))
        finally:
            loop.close()
        return json.dumps({
            "actor": actor, "language": language, "feature_areas": feature_areas,
            "ac_count": len(acceptance_criteria), "acceptance_criteria": acceptance_criteria,
            "testability_score": round(scored.get("testability_score", 0), 2),
            "is_testable": scored.get("is_testable", True),
            "quality_issues": scored.get("issues", [])[:6],
            "suggestions": scored.get("suggestions", [])[:4],
            "final_score": round(scored.get("final_score", 0), 2),
        })
    except Exception as exc:
        return json.dumps({
            "actor": "user", "language": "en", "feature_areas": feature_areas,
            "ac_count": len(acceptance_criteria), "acceptance_criteria": acceptance_criteria,
            "testability_score": 0.6, "is_testable": True,
            "quality_issues": [], "suggestions": [], "final_score": 0.6,
            "_note": f"Lightweight fallback: {exc}",
        })


# ── Tool 2: draft_test_cases ───────────────────────────────────────────────────

class DraftTestCasesInput(BaseModel):
    test_cases: List[TestCaseArg] = Field(
        description="Your initial comprehensive draft of structured test cases."
    )
    acceptance_criteria: List[str] = Field(
        default_factory=list,
        description="The acceptance criteria being tested (used for instant auto-critique).",
    )


@tool("draft_test_cases", args_schema=DraftTestCasesInput)
def draft_test_cases(
    test_cases:          List[TestCaseArg],
    acceptance_criteria: List[str] = None,
) -> str:
    """
    Submit your initial draft of test cases.
    Auto-critique runs instantly — read the 'critique' field and decide:
      quality_ok=True  → call save_test_cases
      quality_ok=False → call refine_test_cases
    Non-terminal.
    """
    tcs      = [tc if isinstance(tc, dict) else tc.model_dump() for tc in test_cases]
    critique = _compute_critique(tcs, acceptance_criteria or [])
    return json.dumps({
        "status":   "draft_received",
        "count":    len(tcs),
        "critique": critique,
        "next_step": (
            "quality_ok=True → call save_test_cases now."
            if critique["quality_ok"] else
            "quality_ok=False → call refine_test_cases addressing every issue, then save_test_cases."
        ),
    })


# ── Tool 3: critique_test_cases ────────────────────────────────────────────────

class CritiqueTestCasesInput(BaseModel):
    test_cases:          List[TestCaseArg] = Field(description="The test cases to critique.")
    acceptance_criteria: List[str]         = Field(default_factory=list)


@tool("critique_test_cases", args_schema=CritiqueTestCasesInput)
def critique_test_cases(
    test_cases:          List[TestCaseArg],
    acceptance_criteria: List[str],
) -> str:
    """
    Explicit quality check. Note: auto-critique is already embedded in draft_test_cases
    and refine_test_cases responses — only call this if you need a standalone re-check.
    Non-terminal.
    """
    tcs = [tc if isinstance(tc, dict) else tc.model_dump() for tc in test_cases]
    return json.dumps(_compute_critique(tcs, acceptance_criteria))


# ── Tool 4: refine_test_cases ──────────────────────────────────────────────────

class RefineTestCasesInput(BaseModel):
    test_cases: List[TestCaseArg] = Field(
        description=(
            "The COMPLETE refined set of test cases "
            "(replaces the current draft entirely — include all cases, not just changed ones)."
        )
    )
    acceptance_criteria: List[str] = Field(
        default_factory=list,
        description="The acceptance criteria (used for instant auto-critique).",
    )
    changes_summary: str = Field(
        default="",
        description="Brief description of what was added/changed and why.",
    )


@tool("refine_test_cases", args_schema=RefineTestCasesInput)
def refine_test_cases(
    test_cases:          List[TestCaseArg],
    acceptance_criteria: List[str] = None,
    changes_summary:     str = "",
) -> str:
    """
    Replace the current draft with a refined set.
    Auto-critique runs instantly — read the 'critique' field and decide:
      quality_ok=True  → call save_test_cases
      quality_ok=False → call save_test_cases anyway (max refinement reached)
    Non-terminal.
    """
    tcs      = [tc if isinstance(tc, dict) else tc.model_dump() for tc in test_cases]
    critique = _compute_critique(tcs, acceptance_criteria or [])
    return json.dumps({
        "status":          "refined",
        "count":           len(tcs),
        "changes_summary": changes_summary,
        "critique":        critique,
        "next_step": (
            "quality_ok=True → call save_test_cases now."
            if critique["quality_ok"] else
            "quality_ok=False but you've refined once — call save_test_cases with your best version."
        ),
    })


# ── Tool 5: save_test_cases (TERMINAL) ────────────────────────────────────────

class SaveTestCasesInput(BaseModel):
    test_cases: List[TestCaseArg] = Field(
        description="The complete, final list of structured test cases."
    )
    user_story_analysis: UserStoryAnalysisArg = Field(
        default_factory=UserStoryAnalysisArg,
        description="Brief analysis: scope and goals.",
    )


@tool("save_test_cases", args_schema=SaveTestCasesInput)
def save_test_cases(
    test_cases:          List[TestCaseArg],
    user_story_analysis: UserStoryAnalysisArg = None,
) -> str:
    """
    Persist the final test cases. TERMINAL ACTION — the agent stops after this call.
    """
    return json.dumps({"saved": True, "count": len(test_cases), "paths": {}})


# ── Tool 6: flag_human_review (TERMINAL) ──────────────────────────────────────

class DraftTestCaseArg(BaseModel):
    id:          str       = Field(default="")
    name:        str       = Field(default="")
    description: str       = Field(default="")
    priority:    str       = Field(default="Medium")
    test_type:   str       = Field(default="Positive")
    tags:        List[str] = Field(default_factory=list)
    steps:       list      = Field(default_factory=list)


class FlagHumanReviewInput(BaseModel):
    reason:      str                      = Field(description="Why human review is needed.")
    draft_cases: List[DraftTestCaseArg]   = Field(default_factory=list)


@tool("flag_human_review", args_schema=FlagHumanReviewInput)
def flag_human_review(
    reason:      str,
    draft_cases: Optional[List[DraftTestCaseArg]] = None,
) -> str:
    """
    Escalate when requirements are genuinely too ambiguous.
    TERMINAL ACTION — the agent stops after this call.
    """
    return json.dumps({"flagged": True, "reason": reason})


# ── Registry ───────────────────────────────────────────────────────────────────

ALL_TOOLS = [
    analyze_story,
    draft_test_cases,
    critique_test_cases,
    refine_test_cases,
    save_test_cases,
    flag_human_review,
]

# Only the tools the LLM is allowed to call.
# analyze_story  — pre-computed, never called by LLM
# critique_test_cases — auto-critique is embedded in draft/refine responses
# save_test_cases — auto-save node handles this without an LLM call
LLM_TOOLS = [
    draft_test_cases,
    refine_test_cases,
    flag_human_review,
]

TERMINAL_TOOLS = frozenset({"save_test_cases", "flag_human_review"})
