import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM
# ============================================================
LLM_TEMPERATURE = 0.3
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS_TEST_SUITE", "2000"))
LLM_TIMEOUT_SECONDS = 60

# ============================================================
# TYPES DE SUITE VALIDES (modèle TestSuite.suite_type)
# ============================================================
VALID_SUITE_TYPES = {"positive", "negative", "boundary"}

# ============================================================
# PRIORITÉ DES SUITES SELON LE NIVEAU DE RISQUE
# (plus petit = exécuté en premier)
# ============================================================
SUITE_EXECUTION_ORDER: dict[str, int] = {
    "critical": 1,
    "high":    2,
    "medium":  3,
    "low":   4,
}

# ============================================================
# NOMBRE MINIMUM DE CAS DE TEST POUR CRÉER UNE SUITE
# ============================================================
MIN_TC_PER_SUITE = 1

# ============================================================
# DEBUG
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
