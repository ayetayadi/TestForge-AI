"""
LLM prompt for the user story refinement pipeline (Step 2 — improvement call).
"""


IMPROVEMENT_PROMPT = """You are a user story quality specialist.

Fix the user story below based on the specific issues identified by the scorer.

ORIGINAL STORY:
{story}

CURRENT ACCEPTANCE CRITERIA:
{acceptance_criteria}

ISSUES FOUND:
{issues}

SUGGESTIONS:
{suggestions}

RULES:
- Keep the exact same language (French stays French, English stays English)
- Keep the actor/role exactly as-is (the "As a [role]" part)
- Keep the core business intent — do not invent new features
- Target testability_score >= {threshold}
- Write at least 2-3 concrete, verifiable acceptance criteria using action verbs (displays, creates, validates, returns)
- Replace any vague terms (quickly, easily, efficiently) with measurable conditions
- NEVER invent specific values (numbers, durations, limits, counts) not stated in the original story
- When a measurable condition is needed but the value is unspecified, use a placeholder instead of guessing:
    [SPECIFY TIME]    → e.g. "The system responds within [SPECIFY TIME]"
    [SPECIFY NUMBER]  → e.g. "displays at least [SPECIFY NUMBER] results"
    [SPECIFY LENGTH]  → e.g. "accepts a minimum of [SPECIFY LENGTH] characters"

Return an improved version that fixes the specific issues listed above."""
