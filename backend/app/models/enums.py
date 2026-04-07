from enum import Enum

class StoryDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED_KEEP = "rejected_keep"
    REJECTED_RELAUNCH = "rejected_relaunch"

class JobStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class JobPhase(str, Enum):
    ANALYZING = "analyzing"
    REFINING = "refining"
    EVALUATING = "evaluating"
    COMPLETED = "completed"