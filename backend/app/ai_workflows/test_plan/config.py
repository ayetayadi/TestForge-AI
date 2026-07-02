import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM
# ============================================================
LLM_TEMPERATURE = 0.3          # Un peu de créativité pour la rédaction, pas trop
LLM_MODEL = "openai/gpt-oss-120b"
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS_TEST_PLAN", "3000"))
LLM_TIMEOUT_SECONDS = 90

# ============================================================
# VALEURS ACCEPTÉES (validation stricte des sorties LLM)
# ============================================================
VALID_ENVIRONMENTS = {"dev", "staging", "prod", "uat"}
VALID_SCOPE_TYPES = {"epic", "sprint", "release", "manual", "spec_document"}

# ============================================================
# ESTIMATION 3 POINTS (en jours ouvrés)
# Formule PERT : E = (O + 4×M + P) / 6
# ============================================================
# Nombre de jours par User Story selon le niveau de risque
DAYS_PER_STORY: dict[str, dict[str, float]] = {
    "critical": {"optimistic": 1.5, "realistic": 2.5, "pessimistic": 4.0},
    "high":    {"optimistic": 1.0, "realistic": 1.5, "pessimistic": 2.5},
    "medium":  {"optimistic": 0.5, "realistic": 1.0, "pessimistic": 1.5},
    "low":   {"optimistic": 0.25, "realistic": 0.5, "pessimistic": 0.75},
}
# Overhead fixe (setup, réunions, reporting)
OVERHEAD_DAYS = 2

# ============================================================
# SEUILS POUR LA RECOMMANDATION DES TYPES DE TEST
# ============================================================
# Si X% des US sont de risque critique ou haute → ajouter le type
REGRESSION_THRESHOLD = 0.30   # ≥30% haute/critique → regression
SECURITY_KEYWORDS = {"authentication", "login", "password", "permission", "role", "auth", "token", "security"}
PERFORMANCE_KEYWORDS = {"performance", "load", "speed", "scalability", "latency", "timeout"}

# ============================================================
# DEBUG
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
