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
MIN_SCORE_THRESHOLD = 0.7
MIN_SIMILARITY_THRESHOLD = 0.65

LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))



# =========================
# ATLAS CLOUD CONFIGURATION
# =========================
ATLAS_API_KEY: str = os.getenv("ATLAS_API_KEY", "")
ATLAS_BASE_URL: str = os.getenv("ATLAS_BASE_URL", "https://api.atlascloud.ai/v1")

GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
GITHUB_MODEL: str = os.getenv("GITHUB_MODEL", "gpt-4o")

# ============================================================
# Tool Configuration
# ============================================================
ENABLE_CACHING = os.getenv("ENABLE_CACHING", "true").lower() == "true"

# ============================================================
# Debug
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"