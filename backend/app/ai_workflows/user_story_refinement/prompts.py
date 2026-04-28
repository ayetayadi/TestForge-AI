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
- KEEP ALL {ac_count} existing acceptance criteria — do not drop any. Rewrite each one to add action verbs and measurable conditions.
- Each criterion must start with an action verb (affiche, retourne, crée, valide, génère, sélectionne, supprime, envoie / displays, returns, creates, validates, generates, selects, deletes, sends)
- Replace any vague terms (quickly, easily, efficiently) with measurable conditions
- NEVER invent specific values (numbers, durations, limits, counts) not stated in the original story
- When a measurable condition is needed but the value is unspecified, use a placeholder:
    [SPECIFY TIME]    → e.g. "retourne une réponse en moins de [SPECIFY TIME]"
    [SPECIFY NUMBER]  → e.g. "affiche au moins [SPECIFY NUMBER] résultats"
    [SPECIFY LENGTH]  → e.g. "accepte un minimum de [SPECIFY LENGTH] caractères"

Return an improved version that fixes the specific issues listed above.
"""
