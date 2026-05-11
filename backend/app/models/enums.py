from enum import Enum

class StoryDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class WorkflowStatus(str, Enum):
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
    V1_DRAFT     = "v1_draft"
    V2_CORRECTED = "v2_corrected"   # Script v2 — locators réels après exécution ReAct
    MANUAL_EDIT  = "manual_edit"    # Édition manuelle par l'utilisateur
    AI_FIX       = "ai_fix"         # Correction automatique par l'agent

# ==============================
# SPEC DOC / TEST PLAN / TEST SUITE
# ==============================

class SpecDocStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"

class TestPlanStatus(str, Enum):
    DRAFT       = "draft"        # Testeur remplit les champs
    AI_PROPOSED = "ai_proposed"  # IA a généré le brouillon, en attente de validation
    APPROVED    = "approved"     # Testeur a validé → déclenche génération suites/cas
    ACTIVE      = "active"       # Génération terminée
    ARCHIVED    = "archived"

class TestCaseType(str, Enum):
    POSITIVE  = "positive"
    NEGATIVE  = "negative"
    EDGE_CASE = "edge_case"

class DependencyType(str, Enum):
    REQUIRES = "requires"  # A doit s'exécuter avant B
    BLOCKS   = "blocks"    # A bloque B si échoue
    RELATED  = "related"   # lien informatif

class TestSuiteStatus(str, Enum):
    DRAFT    = "draft"
    ACTIVE   = "active"
    ARCHIVED = "archived"
    CLOSED   = "closed"

# ==============================
# SCRIPT / DEFECT
# ==============================

class ScriptSource(str, Enum):
    AI_GENERATED = "ai_generated"
    MANUAL       = "manual"
    AI_FIXED     = "ai_fixed"
    V1_DRAFT     = "v1_draft"
    V2_CORRECTED = "v2_corrected"
    MANUAL_EDIT  = "manual_edit"

class DefectSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH     = "high"
    MEDIUM   = "medium"
    LOW      = "low"
    TRIVIAL  = "trivial"

class DefectStatus(str, Enum):
    OPEN        = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED    = "resolved"
    CLOSED      = "closed"
    REOPENED    = "reopened"