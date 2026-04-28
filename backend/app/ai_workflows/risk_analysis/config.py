import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM
# ============================================================
LLM_TEMPERATURE = 0.2          # Risk analysis must be precise, not creative
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS_RISK", "1500"))
LLM_TIMEOUT_SECONDS = 60

# ============================================================
#  — SEUILS DE CLASSIFICATION
# Critical ≥ 4.0 | High 2.5–3.9 | Medium 1.0–2.4 | Low < 1.0
# ============================================================
LEVEL_CRITICAL_MIN = 4.0
LEVEL_HIGH_MIN    = 2.5
LEVEL_MEDIUM_MIN  = 1.0
# Low : risk_score < 1.0

# ============================================================
# BORNES DE PROBABILITÉ ET D'IMPACT
# ============================================================
PROBABILITY_MIN = 0.1
PROBABILITY_MAX = 0.9
IMPACT_MIN = 1
IMPACT_MAX = 5

# ============================================================
# SIGNAUX JIRA → IMPACT DE BASE (indice pour le LLM, non contraignant)
# ============================================================
JIRA_PRIORITY_IMPACT_HINT: dict[str, int] = {
    "highest":  5,
    "critical": 5,
    "high":     4,
    "medium":   3,
    "low":      2,
    "lowest":   1,
}

# ============================================================
# DEBUG
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
