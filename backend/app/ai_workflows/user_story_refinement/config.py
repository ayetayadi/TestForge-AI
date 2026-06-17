import os
from dotenv import load_dotenv

# ============================================================
# CHARGER LE FICHIER .ENV EXPLICITEMENT
# ============================================================
load_dotenv()

# ============================================================
# LLM Configuration
# ============================================================
LLM_TEMPERATURE = 0.3
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS = 2000

# ============================================================
# Agent Configuration
# ============================================================
MAX_ITERATIONS = 2
MIN_SCORE_THRESHOLD = 0.8

# ============================================================
MIN_SIMILARITY_THRESHOLD = 0.70
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))

# ============================================================
# Tool Configuration
# ============================================================
ENABLE_CACHING = os.getenv("ENABLE_CACHING", "true").lower() == "true"

# ============================================================
# Debug
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"