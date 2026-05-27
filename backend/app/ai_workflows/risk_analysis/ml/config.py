"""
Risk-Based Testing — Configuration
Score = Probability (1-5) × Impact (1-5) → 1 à 25
"""

# Échelles P et I
PROBABILITY_MIN = 1
PROBABILITY_MAX = 5
IMPACT_MIN = 1
IMPACT_MAX = 5

# Seuils de priorité
PRIORITY_CRITICAL_MIN = 20   # 20-25
PRIORITY_HIGH_MIN = 12       # 12-19
PRIORITY_MEDIUM_MIN = 6      # 6-11
# Low = 1-5

# Effort par priorité (60/25/10/5 %)
EFFORT_ALLOCATION = {
    "critical": 0.60,
    "high": 0.25,
    "medium": 0.10,
    "low": 0.05,
}

# Techniques de test par priorité
TEST_DEPTH = {
    "critical": {"depth": "comprehensive", "techniques": ["unit", "integration", "e2e", "performance", "security"]},
    "high":     {"depth": "thorough",      "techniques": ["unit", "integration", "e2e"]},
    "medium":   {"depth": "standard",      "techniques": ["unit", "integration"]},
    "low":      {"depth": "smoke",         "techniques": ["smoke"]},
}

# ML
ML_CONFIDENCE_THRESHOLD = 0.50

# Embedding multilingue (français + anglais), 384 dims, ~120 Mo
EMBED_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# LLM
LLM_TEMPERATURE = 0.1
LLM_MODEL = "openai/gpt-oss-120b"
LLM_MAX_TOKENS = 2000
LLM_TIMEOUT_SECONDS = 90
