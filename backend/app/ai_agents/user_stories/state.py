from typing import TypedDict, List, Dict, Any


class UserStoryState(TypedDict, total=False):

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
    # STORY
    # =========================
    raw_story: str
    improved_story: str

    # =========================
    # ACCEPTANCE CRITERIA
    # =========================
    acceptance_criteria: List[str]
    existing_ac: List[str]

    # =========================
    # BEST TRACKING
    # =========================
    best_story: str
    best_ac: List[str]
    best_score: float

    # =========================
    # QUALITY FLAGS
    # =========================
    is_garbage: bool
    guard_failed: bool

    # =========================
    # SCORES
    # =========================
    rule_score: float
    nlp_score: float
    llm_score: float
    ac_score: float

    final_score: float
    initial_score: float
    score_delta: float

    # =========================
    # LLM STATE
    # =========================
    llm_failed: bool
    consecutive_llm_failures: int

    llm_issues: List[str]
    llm_suggestions: List[str]

    # =========================
    # RULE / NLP
    # =========================
    rule_issues: List[str]
    rule_suggestions: List[str]

    nlp_issues: List[str]
    nlp_suggestions: List[str]

    critical_issues: List[str]

    # =========================
    # PIPELINE CONTROL
    # =========================
    iteration: int
    refine_ac_only: bool

    # SIGNAL
    refinement_status: str  # "ok" | "rejected"

    # =========================
    # LANGUAGE
    # =========================
    language: str

    # =========================
    # UI STATE
    # =========================
    current_step: str

    # =========================
    # TRACE & EVENTS
    # =========================
    trace: List[Dict[str, Any]]
    events: List[Dict[str, Any]]

    # =========================
    # TIMING
    # =========================
    timing: Dict[str, float]