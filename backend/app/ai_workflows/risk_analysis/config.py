"""
Risk-Based Testing Configuration
Basé sur le document : Risk = Probability (1-5) × Impact (1-5) = Score (1-25)
"""

# ============================================================
# ÉCHELLES
# ============================================================
# P et I sont des entiers de 1 à 5
PROBABILITY_MIN = 1
PROBABILITY_MAX = 5
IMPACT_MIN = 1
IMPACT_MAX = 5

# Score = P × I → entre 1 et 25
RISK_SCORE_MIN = 1
RISK_SCORE_MAX = 25

# ============================================================
# SEUILS DE PRIORITÉ
# ============================================================
# Extrait du document :
# Critical (20-25) → High (12-19) → Medium (6-11) → Low (1-5)
PRIORITY_CRITICAL_MIN = 20
PRIORITY_HIGH_MIN = 12
PRIORITY_MEDIUM_MIN = 6
# Low = 1 à 5 (pas besoin de constante)

# ============================================================
# EFFORT ALLOCATION
# ============================================================
# Extrait du document : 60% critical, 25% high, 10% medium, 5% low
EFFORT_ALLOCATION = {
    "critical": 0.60,
    "high": 0.25,
    "medium": 0.10,
    "low": 0.05,
}

# ============================================================
# TEST DEPTH PAR PRIORITÉ
# ============================================================
# Extrait du document : quelles techniques de test par priorité
TEST_DEPTH = {
    "critical": {
        "depth": "comprehensive",
        "techniques": ["unit", "integration", "e2e", "performance", "security"],
    },
    "high": {
        "depth": "thorough",
        "techniques": ["unit", "integration", "e2e"],
    },
    "medium": {
        "depth": "standard",
        "techniques": ["unit", "integration"],
    },
    "low": {
        "depth": "smoke",
        "techniques": ["smoke"],
    },
}

# ============================================================
# ML CONFIGURATION
# ============================================================
# Seuil de confiance en dessous duquel on ignore la prédiction ML
ML_CONFIDENCE_THRESHOLD = 0.40

# Nombre de features max pour TF-IDF
TFIDF_MAX_FEATURES = 500

# ============================================================
# LLM CONFIGURATION
# ============================================================
LLM_TEMPERATURE = 0.1  # Bas = réponses plus déterministes
LLM_MODEL = "openai/gpt-oss-120b"
LLM_MAX_TOKENS = 2000
LLM_TIMEOUT_SECONDS = 90