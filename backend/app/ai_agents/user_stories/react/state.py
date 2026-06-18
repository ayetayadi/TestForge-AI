from typing import TypedDict, List, Dict, Any, Optional


class UserStoryReactState(TypedDict, total=False):

    # =========================
    # IDENTIFICATION
    # =========================
    job_id: str
    jira_id: str

    # =========================
    # CACHE CONTROL
    # =========================
    use_cache: bool

    # =========================
    # RAW INPUT
    # =========================
    raw_story: str

    # =========================
    # REFINED OUTPUT
    # =========================
    improved_story: Optional[str]
    acceptance_criteria: List[str]
    existing_ac: List[str]

    # =========================
    # SCORES
    # =========================
    initial_score: float
    final_score: float
    rule_score: float
    nlp_score: float
    llm_score: float
    ac_score: float
    score_delta: float
    best_score: float
    best_story: Optional[str]
    best_ac: List[str]

    # =========================
    # REACT AGENT INTERNALS
    # =========================
    iterations: int                  # number of refinement loops done
    reasoning: List[str]             # Thought/Action/Observation log
    react_decision: str              # "approved" | "rejected" | "pending"

    # =========================
    # ISSUES & SUGGESTIONS
    # =========================
    llm_issues: List[str]
    llm_suggestions: List[str]
    rule_issues: List[str]
    rule_suggestions: List[str]
    nlp_issues: List[str]
    nlp_suggestions: List[str]
    critical_issues: List[str]

    # =========================
    # QUALITY FLAGS
    # =========================
    is_garbage: bool
    guard_failed: bool
    llm_failed: bool
    consecutive_llm_failures: int

    # =========================
    # PIPELINE CONTROL
    # =========================
    iteration: int
    refine_ac_only: bool
    refinement_status: str

    # =========================
    # TESTABILITY
    # =========================
    testability_score: float
    is_testable: bool
    testability_issues: List[str]
    input_quality: str

    # =========================
    # LANGUAGE
    # =========================
    language: str

    # =========================
    # LLM METRICS
    # =========================
    llm_calls: int
    model_used: Optional[str]
    prompt_tokens: int
    completion_tokens: int

    # =========================
    # TRACE & TIMING
    # =========================
    trace: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    timing: Dict[str, float]

    # =========================
    # MISC
    # =========================
    is_retry: bool
    current_step: str
    status: str
