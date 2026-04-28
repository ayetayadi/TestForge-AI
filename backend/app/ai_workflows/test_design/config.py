import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM
# ============================================================
LLM_TEMPERATURE = 0.4          # Un peu plus créatif que le refinement (génération, pas correction)
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS_TEST_DESIGN", "4000"))  # Les TCs sont verbeux

# ============================================================
# COUVERTURE MINIMALE
# ============================================================
MIN_COVERAGE_THRESHOLD = 0.80  # 80% des ACs doivent être couverts par au moins un TC

# ============================================================
# NOMBRE DE CAS DE TEST PAR NIVEAU DE RISQUE
# Critique ≥4.0 | Haute 2.5–3.9 | Moyenne 1.0–2.4 | Faible <1.0
# ============================================================
RISK_LEVEL_TEST_COUNTS = {
    "critique": {"positive": 3, "negative": 3, "edge_case": 2},
    "haute":    {"positive": 2, "negative": 2, "edge_case": 2},
    "moyenne":  {"positive": 2, "negative": 1, "edge_case": 1},
    "faible":   {"positive": 1, "negative": 1, "edge_case": 0},
    # fallback si level inconnu
    "default":  {"positive": 2, "negative": 1, "edge_case": 1},
}

# ============================================================
# TIMEOUT
# ============================================================
LLM_TIMEOUT_SECONDS = 90       # Génération multi-TC prend plus de temps qu'un seul raffinement

# ============================================================
# DEBUG
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
