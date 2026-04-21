from enum import Enum

class StoryDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class AgentStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# ==============================
# TEST EXECUTION
# ==============================

class TestRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TestResultStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"

class StepType(str, Enum):
    THINK = "think"
    ACT = "act"
    OBSERVE = "observe"

class StepStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"

class ScriptValidationStatus(str, Enum):
    NOT_VALIDATED = "not_validated"
    VALID = "valid"
    INVALID = "invalid"

class ScriptSource(str, Enum):
    V1_DRAFT     = "v1_draft"       # Script v1 — placeholders [TESTFORGE: ...]
    V2_CORRECTED = "v2_corrected"   # Script v2 — locators réels après exécution ReAct
    MANUAL_EDIT  = "manual_edit"    # Édition manuelle par l'utilisateur
    AI_FIX       = "ai_fix"         # Correction automatique par l'agent