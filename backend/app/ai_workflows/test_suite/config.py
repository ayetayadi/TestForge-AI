import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM
# ============================================================
LLM_TEMPERATURE = 0.3
LLM_MODEL = "openai/gpt-oss-120b"
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS_TEST_SUITE", "2000"))
LLM_TIMEOUT_SECONDS = 60

# ============================================================
# STRATÉGIES DE GROUPEMENT
# risk_level  → une suite par niveau de risque (critique, haute, moyenne, faible)
# test_type   → une suite par type (positive, negative, edge_case)
# feature     → une suite par epic/composant Jira
# mixed       → risk_level en priorité, puis test_type
# ============================================================
GROUPING_STRATEGY = os.getenv("SUITE_GROUPING_STRATEGY", "risk_level")

# ============================================================
# TYPES DE SUITE VALIDES (modèle TestSuite.suite_type)
# ============================================================
VALID_SUITE_TYPES = {
    "feature", "epic", "sprint",
    "smoke", "regression", "negative",
    "security", "performance", "e2e",
}

# ============================================================
# PRIORITÉ DES SUITES SELON LE NIVEAU DE RISQUE
# (plus petit = exécuté en premier)
# ============================================================
SUITE_EXECUTION_ORDER: dict[str, int] = {
    "critical": 1,
    "high":    2,
    "medium":  3,
    "low":   4,
    "smoke":    0,       # smoke toujours en premier
    "security": 1,
    "regression": 5,
}

# ============================================================
# NOMBRE MINIMUM DE CAS DE TEST POUR CRÉER UNE SUITE
# ============================================================
MIN_TC_PER_SUITE = 1

# ============================================================
# DEBUG
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
