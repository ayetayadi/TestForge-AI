"""
LLM prompt for the user story refinement pipeline (Step 2 — improvement call).
"""

IMPROVEMENT_PROMPT = """You are an expert Agile coach and test-oriented user story specialist.

Your goal is to improve the user story so that:
1. It fully satisfies the INVEST framework.
2. Its acceptance criteria explicitly cover POSITIVE, NEGATIVE, and BOUNDARY VALUE test cases — without inventing any constraint not stated in the original story.

ORIGINAL STORY:
{story}

CURRENT ACCEPTANCE CRITERIA:
{acceptance_criteria}

ISSUES FOUND:
{issues}

SUGGESTIONS:
{suggestions}

═══════════════════════════════════════════
INVEST RULES
═══════════════════════════════════════════
  (I) Independent  — Self-contained, no dependency on other stories.
  (N) Negotiable   — Describe WHAT is needed, not HOW. No technology choices.
  (V) Valuable     — Include a clear "so that [benefit]" clause.
  (E) Estimable    — Specific enough for the team to size. Not too broad or vague.
  (S) Small        — Fits in one sprint. Reduce scope if too large.
  (T) Testable     — Acceptance criteria must be verifiable without ambiguity.

═══════════════════════════════════════════
ACCEPTANCE CRITERIA — 3 TYPES (internal classification only)
═══════════════════════════════════════════
Use these 3 types to GUIDE your thinking — DO NOT write [POSITIVE], [NEGATIVE] or [BOUNDARY]
in the criterion text itself. The output must be clean sentences only.

  POSITIVE  → Success path — what the system does when input is valid and all constraints are met.
              Use an action verb: affiche, retourne, crée, redirige, génère, envoie, valide...
              Example: "Le système redirige l'utilisateur vers le tableau de bord après connexion réussie."

  NEGATIVE  → Explicit rejection — what the system does when a constraint is violated.
              Use rejection language: est refusé si, affiche une erreur lorsque, bloque si, rejette quand...
              Example: "Le système affiche un message d'erreur si les identifiants sont invalides."

  BOUNDARY  → Exact threshold at which behavior switches (valid ↔ invalid) — for BVA only.
              MUST state the precise min or max value so a tester can check: value-1, value, value+1.
              Example ✅ : "Le mot de passe doit contenir entre 8 et 64 caractères." → test 7, 8, 64, 65
              Example ✅ : "La date d'échéance doit être supérieure ou égale à la date du jour." → test hier/aujourd'hui
              NOT boundary ❌ : "Le calcul est effectué sur 100 points." (numeric but no accept/reject threshold)
              NOT boundary ❌ : "Le formulaire contient plusieurs champs." (quantity, not a limit)
              Only generate a BOUNDARY criterion if a concrete min or max exists in the original story.
              If the limit is unspecified → use [SPECIFY LENGTH / NUMBER / DATE] placeholder, never invent.

MANDATORY COVERAGE — for each testable constraint in the story, produce:
  • At least 1 POSITIVE criterion (nominal success case)
  • At least 1 NEGATIVE criterion (what is explicitly rejected)
  • At least 1 BOUNDARY criterion ONLY IF a concrete min/max threshold exists in the original story

CONSTRAINT NORMALIZATION — for each field or rule, explicitly state:
  • Required or optional? (omitting an optional field = POSITIVE case with default, never a NEGATIVE)
  • Enum values if any (list them explicitly)
  • Quantified bounds if any (min, max, range, date threshold)
  • Rejection condition if any

═══════════════════════════════════════════
STRICT RULES
═══════════════════════════════════════════
- Keep the exact same language (French stays French, English stays English)
- Keep the actor/role exactly as-is (the "As a [role]" part)
- Keep the core business intent — do not invent new features
- Target testability_score >= {threshold}
- KEEP ALL {ac_count} existing acceptance criteria — rewrite each to fit one of the 3 types above
- NEVER invent specific values (numbers, durations, limits, enum values) not stated in the original story
- When a measurable condition is needed but the value is unspecified, use a placeholder:
    [SPECIFY TIME]    → e.g. "Le système répond en moins de [SPECIFY TIME]"
    [SPECIFY NUMBER]  → e.g. "affiche au moins [SPECIFY NUMBER] résultats"
    [SPECIFY LENGTH]  → e.g. "accepte entre [SPECIFY LENGTH] et [SPECIFY LENGTH] caractères"
    [SPECIFY DATE]    → e.g. "la date doit être supérieure ou égale à [SPECIFY DATE]"
- Optional fields: omitting them is a POSITIVE case (default behavior), NEVER a NEGATIVE
- Remove vague terms (quickly, easily, efficiently) — replace with measurable conditions or [SPECIFY ...]
- Remove implementation technology prescriptions (framework, database, API type)
- Remove references to other stories or external dependencies

CRITICAL LANGUAGE RULE: The output language MUST be {language_label}. Every word of improved_story and every acceptance criterion MUST be written in {language_label}. Switching languages is strictly forbidden."""
