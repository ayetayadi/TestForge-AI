import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM Configuration
# ============================================================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
# Must be a model with tool/function calling support for the ReAct agent
LLM_MODEL = os.getenv("PLAYWRIGHT_LLM_MODEL", "openai/gpt-oss-120b")
LLM_TEMPERATURE = 0.1

# ============================================================
# Script Generator Configuration
# ============================================================
PLACEHOLDER_PREFIX = "TESTFORGEAI"

# ============================================================
# ReAct Agent Configuration
# ============================================================
MAX_REACT_ITERATIONS = 20

# ============================================================
# MCP Playwright Configuration
# ============================================================
MCP_PLAYWRIGHT_SERVER_URL = os.getenv("MCP_PLAYWRIGHT_SERVER_URL", "http://localhost:8931")
APP_BASE_URL = os.getenv("TEST_APPLICATION_URL", "http://localhost:3000")
MCP_PLAYWRIGHT_TIMEOUT = int(os.getenv("MCP_PLAYWRIGHT_TIMEOUT", "60"))

# ============================================================
# Debug
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
