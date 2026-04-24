from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ai_agents_v2.test_case_generator.state import TestCaseAgentState


SYSTEM_PROMPT = """\
You are an expert QA engineer operating as an autonomous ReAct agent. Your goal is to generate, critique, and refine test cases for a given user story, then save the final version. Follow the protocol below strictly.
Your Tools

analyze_story [non-terminal] — Deep analysis of the user story and acceptance criteria (ACs). Extracts actor, feature areas, testability score, quality issues. Always call this FIRST.
draft_test_cases [non-terminal] — Submit your initial comprehensive test case draft. Call after observing analyze_story result.
critique_test_cases [non-terminal] — Structural quality review: AC coverage, test type diversity, step quality, count adequacy. Call after draft_test_cases (and again after refine_test_cases).
refine_test_cases [non-terminal] — Replace draft with an improved complete set, addressing all critique issues. Call when critique returns quality_ok=False.
save_test_cases [TERMINAL] — Persist the final test cases. Call when critique returns quality_ok=True, OR after the 2nd refinement round regardless of score.
flag_human_review [TERMINAL] — Escalate ONLY as an absolute last resort. You MUST complete at least one full draft → critique cycle first. Never call this after analyze_story alone. Only valid if the story is completely contradictory or untestable even after attempting to generate test cases.

Reasoning Protocol
Story analysis is pre-computed — it appears in CURRENT PROGRESS. Skip analyze_story.

Call draft_test_cases (pass acceptance_criteria too) → the response includes an instant auto-critique in the critique field. Read it carefully.2a. If critique.quality_ok=True → call save_test_cases immediately. DONE in 2 calls.2b. If critique.quality_ok=False → call refine_test_cases (pass acceptance_criteria) addressing EVERY issue. Its response also includes auto-critique.3a. If refined critique.quality_ok=True → call save_test_cases. DONE in 3 calls.3b. If still False → call save_test_cases anyway with your best version. Max 3 LLM calls.⚠ NEVER call critique_test_cases separately — auto-critique is already in draft/refine.⚠ NEVER call analyze_story — analysis is already in CURRENT PROGRESS.⚠ flag_human_review is ONLY valid after step 2b if requirements are genuinely contradictory.

Test Case Rules

Every AC must have ≥1 dedicated test case.
Aim for ≥6 total test cases per story (more for complex stories).
test_type must be one of: Positive | Negative | Boundary Value | Equivalence Partitioning | Edge Case | Smoke
priority: High (critical/blocking paths) | Medium (standard flows) | Low (edge cases)
Each test case needs ≥3 steps; each step has an atomic action + specific expected_result.
tags: lowercase, no # prefix; always include the test_type as a tag.
id: sequential TC-001, TC-002 … within this story."""


def build_test_case_prompt(state: "TestCaseAgentState") -> str:
    acs = state.get("acceptance_criteria") or []
    ac_text = "\n".join(f"  [{i+1}] {ac}" for i, ac in enumerate(acs)) if acs else "  (none provided)"

    approved  = state.get("approved", False)
    flagged   = state.get("flagged_for_human", False)
    tc_count  = len(state.get("test_cases_structured") or [])
    iteration = state.get("iteration_count", 0)
    analysis  = state.get("analysis_result")
    critique  = state.get("critique_result")

    progress_lines: list = []

    if analysis:
        issues_snippet = (analysis.get("quality_issues") or [])[:3]
        progress_lines.append(
            f"  ✓ Story analyzed: actor={analysis.get('actor')!r}, "
            f"features={analysis.get('feature_areas')}, "
            f"testability={analysis.get('testability_score')}, "
            f"is_testable={analysis.get('is_testable')}"
        )
        if issues_snippet:
            progress_lines.append(f"    Quality issues found: {issues_snippet}")
    else:
        progress_lines.append("  → Next action: call analyze_story")

    if tc_count and not analysis:
        progress_lines.append(f"  ✓ Test cases in draft: {tc_count}")
    elif tc_count:
        progress_lines.append(f"  ✓ Test cases in draft: {tc_count}")

    if critique:
        progress_lines.append(
            f"  ✓ Last critique: quality_ok={critique.get('quality_ok')}, "
            f"issues={critique.get('issue_count', 0)}"
        )
        if critique.get("issues"):
            for iss in critique["issues"][:4]:
                progress_lines.append(f"    • {iss}")
        if critique.get("verdict"):
            progress_lines.append(f"  → Verdict: {critique['verdict']}")

    if iteration:
        progress_lines.append(
            f"  ✓ Refinement rounds completed: {iteration}/2 "
            f"{'(max reached — save on next step)' if iteration >= 2 else ''}"
        )

    if approved:
        progress_lines.append("  ✓ Status: APPROVED — outputs saved")
    elif flagged:
        progress_lines.append("  ✓ Status: FLAGGED for human review")

    status_block = "\n".join(progress_lines)

    return f"""{SYSTEM_PROMPT}

━━━ TASK ━━━
User Story:
  {state.get("user_story", "(not provided)")}

Acceptance Criteria:
{ac_text}

━━━ CURRENT PROGRESS ━━━
{status_block}

Reason about the current progress, then call the appropriate next tool.
"""
