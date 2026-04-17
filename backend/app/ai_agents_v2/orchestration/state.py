# ============================================================
# ai_agents_v2/orchestration/state.py (CORRIGÉ)
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

from app.ai_agents_v2.user_story_refinement.config import LLM_MODEL, LLM_TEMPERATURE


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
    duration_seconds: Optional[float]  # ✅ Seulement ici


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
    version_id: str
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
    # TIMING (seulement started_at pour référence, pas de durée)
    # ============================================================
    started_at: str           # ISO format UTC datetime
    
    # ============================================================
    # AGENT METADATA
    # ============================================================
    agent_version: str
    model_used: str
    temperature: float
    
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
    version_id: str,
    story: str,
    acceptance_criteria: List[str] = None,
    language: str = "en",
    actor: str = "",
    agent_version: str = "2.0",
    model_used: str = LLM_MODEL,
    temperature: float = LLM_TEMPERATURE,
) -> OrchestrationState:
    """
    Create initial orchestration state.
    
    Args:
        jira_id: Jira issue ID
        version_id: Version ID
        story: Original story
        acceptance_criteria: Input AC (optional)
        language: Input language (default: "en")
        actor: Input actor (default: "")
        agent_version: Agent version (default: "2.0")
        model_used: LLM model (default: "gpt-oss-20b")
        temperature: LLM temperature (default: 0.3)
        
    Returns:
        Initial OrchestrationState
    """
    now = datetime.utcnow().isoformat()
    
    return {
        # Identification
        "jira_id": jira_id,
        "version_id": version_id,
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
        
        # Timing (seulement started_at)
        "started_at": now,
        
        # Metadata
        "agent_version": agent_version,
        "model_used": model_used,
        "temperature": temperature,
        "pipeline_version": "1.0",
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def mark_step_complete(
    state: OrchestrationState,
    step_name: str
) -> OrchestrationState:
    """
    Marque une étape comme complétée.
    """
    state["steps_completed"] = state.get("steps_completed", 0) + 1
    state["current_step"] = step_name
    return state


def mark_pipeline_complete(state: OrchestrationState) -> OrchestrationState:
    """
    Marque le pipeline ENTIER comme complété.
    ✅ Ne calcule PAS la durée (c'est fait dans l'agent)
    """
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
    
    return state