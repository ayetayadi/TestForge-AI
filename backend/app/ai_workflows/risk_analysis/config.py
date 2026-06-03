import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM
# Uses Groq llama-3.3-70b-versatile — native structured output,
# fastest available, no slash so routes to the Groq pool directly.
# max_tokens is kept small because the output schema is flat ints
# + two short strings; no verbose reasoning requested.
# ============================================================
LLM_TEMPERATURE = 0.1
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS = 800
LLM_TIMEOUT_SECONDS = 60

# ============================================================
# P and I SCALES  (ISTQB Risk-Based Testing — 1-5 ordinal scale)
# ============================================================
PROBABILITY_MIN = 1
PROBABILITY_MAX = 5
IMPACT_MIN = 1
IMPACT_MAX = 5

# ============================================================
# CLASSIFICATION THRESHOLDS  (ISTQB 5×5 matrix, 25-point scale)
#
#   Critical : 15 – 25
#   High     :  9 – 14
#   Medium   :  4 –  8
#   Low      :  1 –  3
# ============================================================
LEVEL_CRITICAL_MIN = 15
LEVEL_HIGH_MIN = 9
LEVEL_MEDIUM_MIN = 4

# ============================================================
# PROBABILITY SUB-FACTORS  (derivable from user story text)
# P = round( avg(story_complexity, ac_complexity, dependencies, clarity) )
# ============================================================
PROBABILITY_FACTORS = {
    "story_complexity": "1=trivial display, 3=some conditions/rules, 5=complex logic/algorithms",
    "ac_complexity":    "1=1-2 simple ACs, 3=3-5 with detail, 5=6+ ACs with edge cases",
    "dependencies":     "1=standalone, 3=one external system, 5=many systems (payment, email…)",
    "clarity":          "1=perfectly clear, 3=some vague terms, 5=unclear/missing details",
}

# ============================================================
# IMPACT SUB-FACTORS  (ISTQB standard impact dimensions)
# I = round( avg(users_affected, revenue, safety, reputation) )
# ============================================================
IMPACT_FACTORS = {
    "users_affected": "1=admin/internal, 3=department/group, 5=all end-users/public",
    "revenue":        "1=no impact, 3=indirect (analytics), 5=direct (payments/orders)",
    "safety":         "1=cosmetic only, 3=data loss risk, 5=security breach/legal",
    "reputation":     "1=internal only, 3=visible to clients, 5=public-facing",
}

# ============================================================
# EFFORT ALLOCATION BY RISK LEVEL  (ISTQB §5.2.4)
# ============================================================
EFFORT_ALLOCATION = {
    "critical": 0.60,
    "high":     0.25,
    "medium":   0.10,
    "low":      0.05,
}
