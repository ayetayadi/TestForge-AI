import os
from dotenv import load_dotenv

# ============================================================
# CHARGER LE FICHIER .ENV EXPLICITEMENT
# ============================================================
load_dotenv()

# ============================================================
# LLM Configuration
# ============================================================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
LLM_TEMPERATURE = 0.3
LLM_MODEL="openai/gpt-oss-120b"

# ============================================================
# Agent Configuration
# ============================================================
MAX_ITERATIONS = 2
MIN_SCORE_THRESHOLD = 0.8
MIN_SIMILARITY_THRESHOLD = 0.65

LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))

# ============================================================
# Tool Configuration
# ============================================================
ENABLE_CACHING = os.getenv("ENABLE_CACHING", "true").lower() == "true"

# ============================================================
# Debug
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"