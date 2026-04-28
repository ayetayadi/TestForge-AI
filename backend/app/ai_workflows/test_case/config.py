import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM
# ============================================================
LLM_TEMPERATURE = 0.4
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS_TEST_CASE", "5000"))
LLM_TIMEOUT_SECONDS = 120      # Gherkin + steps + test_data = verbose

# ============================================================
# COUVERTURE MINIMALE DES CRITÈRES D'ACCEPTATION
# ============================================================
MIN_AC_COVERAGE = 0.80         # 80% des ACs doivent être couverts

# ============================================================
# NOMBRE DE CAS PAR NIVEAU DE RISQUE ()
# Critique ≥4.0 | Haute 2.5–3.9 | Moyenne 1.0–2.4 | Faible <1.0
# ============================================================
RISK_LEVEL_TEST_COUNTS: dict[str, dict[str, int]] = {
    "critique": {"positive": 3, "negative": 3, "edge_case": 2},
    "haute":    {"positive": 2, "negative": 2, "edge_case": 2},
    "moyenne":  {"positive": 2, "negative": 1, "edge_case": 1},
    "faible":   {"positive": 1, "negative": 1, "edge_case": 0},
    "default":  {"positive": 2, "negative": 1, "edge_case": 1},
}

# ============================================================
# VALIDATION GHERKIN
# ============================================================
GHERKIN_KEYWORDS = {"given", "when", "then", "and", "but"}
MIN_GHERKIN_STEPS = 3          # Au moins Given + When + Then

# ============================================================
# DEBUG
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
