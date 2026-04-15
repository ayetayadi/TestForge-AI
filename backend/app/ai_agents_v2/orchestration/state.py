# ============================================================
# ai_agents_v2/orchestration/state.py (SANS REQUIRED)
# ============================================================
"""
Orchestration State - Global state for all pipeline steps.

✅ COMPLETE: All agent outputs tracked
✅ PRODUCTION: Monitoring and versioning metadata
✅ SIMPLE: No Required/NotRequired complexity
"""

from typing import TypedDict, List, Optional
from datetime import datetime
import sys


# ============================================================
# INPUT STATE
# ============================================================
class UserStoryInput(TypedDict, total=False):
    """Input story metadata."""
    story: str
    acceptance_criteria: List[str]
    language: str
    actor: str


# ============================================================
# AGENT RESULT
# ============================================================
class UserStoryImprovementResult(TypedDict, total=False):
    """
    Résultat de l'agent d'amélioration.
    Tous les champs sont optionnels pour éviter les erreurs de typage strict.
    """
    
    # ============================================================
    # MAIN OUTPUTS
    # ============================================================
    improved_story: str
    acceptance_criteria: List[str]
    
    # ============================================================
    # SCORES
    # ============================================================
    score: float
    initial_score: float
    final_score: float
    testability_score: float
    is_testable: bool
    
    # ============================================================
    # VALIDATIONS
    # ============================================================
    valid: bool
    is_improved: bool
    language: str
    language_consistent: bool
    role_preserved: bool
    original_actor: str
    improved_actor: str
    similarity: float
    
    # ============================================================
    # TESTABILITY DETAILS
    # ============================================================
    testability_issues: List[str]
    testability_issues_fixed: List[str]
    
    # ============================================================
    # CONSTRAINTS
    # ============================================================
    violations: List[str]
    
    # ============================================================
    # EXECUTION METADATA
    # ============================================================
    iterations: int
    agent_status: str  # "success" | "best_effort" | "error"
    error: Optional[str]


# ============================================================
# ORCHESTRATION STATE
# ============================================================
class OrchestrationState(TypedDict, total=False):
    """
    État global de l'orchestrateur.
    Tous les champs sont optionnels pour éviter les erreurs de typage strict.
    """
    
    # ============================================================
    # IDENTIFICATION & CONTROL
    # ============================================================
    jira_id: str
    job_id: str
    timestamp: str
    current_step: str  # "story_improvement" | "test_case" | etc.
    
    # ============================================================
    # INPUT (WITH METADATA)
    # ============================================================
    original_story: str
    input_acceptance_criteria: List[str]
    input_language: str
    input_actor: str
    
    # ============================================================
    # AGENT RESULTS
    # ============================================================
    user_story_improvement: Optional[UserStoryImprovementResult]
    
    # ============================================================
    # ERROR HANDLING
    # ============================================================
    errors: List[str]
    status: str  # "processing" | "success" | "failed"
    
    # ============================================================
    # EXECUTION METADATA
    # ============================================================
    steps_completed: int
    retry_count: int
    
    # ============================================================
    # TIMING
    # ============================================================
    started_at: str           # ISO format UTC datetime
    completed_at: Optional[str]
    duration_seconds: Optional[float]
    
    # ============================================================
    # AGENT METADATA
    # ============================================================
    agent_version: str
    model_used: str
    temperature: float
    max_iterations: int
    
    # ============================================================
    # PIPELINE VERSION
    # ============================================================
    pipeline_version: str
    python_version: str


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def create_initial_state(
    jira_id: str,
    job_id: str,
    story: str,
    acceptance_criteria: List[str] = None,
    language: str = "en",
    actor: str = "",
    agent_version: str = "2.0",
    model_used: str = "gpt-4o",
    temperature: float = 0.3,
    max_iterations: int = 3,
) -> OrchestrationState:
    """
    Create initial orchestration state.
    
    Args:
        jira_id: Jira issue ID
        job_id: Job ID
        story: Original story
        acceptance_criteria: Input AC (optional)
        language: Input language (default: "en")
        actor: Input actor (default: "")
        agent_version: Agent version (default: "2.0")
        model_used: LLM model (default: "gpt-4o")
        temperature: LLM temperature (default: 0.3)
        max_iterations: Max iterations (default: 3)
        
    Returns:
        Initial OrchestrationState
    """
    now = datetime.utcnow().isoformat()
    
    return {
        # Identification
        "jira_id": jira_id,
        "job_id": job_id,
        "timestamp": now,
        "current_step": "story_improvement",
        
        # Input
        "original_story": story,
        "input_acceptance_criteria": acceptance_criteria or [],
        "input_language": language,
        "input_actor": actor,
        
        # Results
        "user_story_improvement": None,
        
        # Execution
        "errors": [],
        "status": "processing",
        "steps_completed": 0,
        "retry_count": 0,
        
        # Timing
        "started_at": now,
        "completed_at": None,
        "duration_seconds": None,
        
        # Metadata
        "agent_version": agent_version,
        "model_used": model_used,
        "temperature": temperature,
        "max_iterations": max_iterations,
        "pipeline_version": "1.0",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def mark_step_complete(
    state: OrchestrationState,
    step_name: str
) -> OrchestrationState:
    """
    Marque une étape comme complétée.
    Ne calcule PAS la durée finale.
    """
    state["steps_completed"] = state.get("steps_completed", 0) + 1
    state["current_step"] = step_name
    return state


def mark_pipeline_complete(state: OrchestrationState) -> OrchestrationState:
    """
    Marque le pipeline ENTIER comme complété.
    Calcule la durée totale.
    À appeler UNIQUEMENT dans le nœud final.
    """
    now = datetime.utcnow()
    started = datetime.fromisoformat(state.get("started_at", now.isoformat()))
    duration = (now - started).total_seconds()
    
    state["completed_at"] = now.isoformat()
    state["duration_seconds"] = duration
    state["status"] = "success"
    state["current_step"] = "done"
    
    return state


def mark_failed(
    state: OrchestrationState,
    error: str
) -> OrchestrationState:
    """
    Mark pipeline as failed.
    
    Args:
        state: Orchestration state
        error: Error message
        
    Returns:
        Updated state
    """
    errors = state.get("errors", [])
    errors.append(error)
    state["errors"] = errors
    state["status"] = "failed"
    
    now = datetime.utcnow()
    state["completed_at"] = now.isoformat()
    
    started = datetime.fromisoformat(state.get("started_at", now.isoformat()))
    duration = (now - started).total_seconds()
    state["duration_seconds"] = duration
    
    return state