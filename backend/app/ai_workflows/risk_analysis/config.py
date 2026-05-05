import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM
# ============================================================
LLM_TEMPERATURE = 0.2
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS_RISK", "1500"))
LLM_TIMEOUT_SECONDS = 240

# ============================================================
# ÉCHELLES CONFORMES AU DOCUMENT ORIGINAL
# P et I sont tous les deux sur une échelle 1-5
# ============================================================
PROBABILITY_MIN = 1
PROBABILITY_MAX = 5
IMPACT_MIN = 1
IMPACT_MAX = 5

# ============================================================
# SEUILS DE CLASSIFICATION (Document original)
# Critical ≥ 20 | High 12-19 | Medium 6-11 | Low 1-5
# ============================================================
LEVEL_CRITICAL_MIN = 20
LEVEL_HIGH_MIN = 12
LEVEL_MEDIUM_MIN = 6
# Low : risk_score 1-5

# ============================================================
# FACTEURS DE PROBABILITÉ (Document original)
# ============================================================
PROBABILITY_FACTORS = {
    "complexity": {
        "simple_crud": 1,
        "business_logic": 3,
        "algorithms_integrations": 5
    },
    "change_rate": {
        "stable_6months": 1,
        "monthly": 3,
        "weekly_daily": 5
    },
    "developer_experience": {
        "senior_expert": 1,
        "mid_level": 3,
        "junior_new": 5
    },
    "technical_debt": {
        "clean_code": 1,
        "some_debt": 3,
        "legacy_no_tests": 5
    }
}

# ============================================================
# FACTEURS D'IMPACT (Document original)
# ============================================================
IMPACT_FACTORS = {
    "users_affected": {
        "admin_only": 1,
        "department": 3,
        "all_users": 5
    },
    "revenue": {
        "none": 1,
        "indirect": 3,
        "direct_checkout": 5
    },
    "safety": {
        "convenience": 1,
        "data_loss": 3,
        "physical_harm": 5
    },
    "reputation": {
        "internal": 1,
        "industry": 3,
        "public_scandal": 5
    }
}