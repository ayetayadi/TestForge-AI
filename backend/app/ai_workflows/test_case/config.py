import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM
# ============================================================
LLM_TEMPERATURE = 0.4
LLM_MODEL = "openai/gpt-oss-20b"
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS_TEST_CASE", "6000"))
LLM_TIMEOUT_SECONDS = 120      # Gherkin + steps + test_data = verbose

# ============================================================
# MINIMUM ACCEPTANCE CRITERIA COVERAGE
# ============================================================
MIN_AC_COVERAGE = 0.80         # 80% of ACs must be covered

# ============================================================
# TEST CASE COUNTS BY RISK LEVEL
# Critical ≥4.0 | High 2.5–3.9 | Medium 1.0–2.4 | Low <1.0
# ============================================================
RISK_LEVEL_TEST_COUNTS: dict[str, dict[str, int]] = {
    "critical": {"positive": 1, "negative": 1, "boundary": 1},
    "high":     {"positive": 1, "negative": 1, "boundary": 1},
    "medium":   {"positive": 1, "negative": 1, "boundary": 0},
    "low":      {"positive": 1, "negative": 0, "boundary": 0},
    "default":  {"positive": 1, "negative": 1, "boundary": 0},
}
# ============================================================
# GHERKIN VALIDATION
# ============================================================
GHERKIN_KEYWORDS = {"given", "when", "then", "and", "but"}
MIN_GHERKIN_STEPS = 3          # At least Given + When + Then

# ============================================================
# DEBUG
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
