import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LLM
# ============================================================
LLM_TEMPERATURE = 0.4
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS_TEST_CASE", "6000"))
LLM_TIMEOUT_SECONDS = 240      # Gherkin + steps + test_data = verbose

# ============================================================
# MINIMUM ACCEPTANCE CRITERIA COVERAGE
# ============================================================
MIN_AC_COVERAGE = 0.80         # 80% of ACs must be covered

# ============================================================
# COUNT ESTIMATION
# count = ceil(total_ACs / AC_TO_TC_RATIO), minimum 1
# ============================================================
AC_TO_TC_RATIO = 2.5

# ============================================================
# CORRECTION LOOP
# Max iterations when coverage < 80%
# ============================================================
MAX_CORRECTION_ITERATIONS = 2

# ============================================================
# GHERKIN VALIDATION
# ============================================================
GHERKIN_KEYWORDS = {"given", "when", "then", "and", "but"}
MIN_GHERKIN_STEPS = 3          # At least Given + When + Then

# ============================================================
# DEBUG
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
