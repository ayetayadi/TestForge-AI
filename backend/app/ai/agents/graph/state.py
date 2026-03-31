from typing import TypedDict, List, Optional, Literal, Any

class UserStoryState(TypedDict):
    # ── Inputs ───────────────────────────────────────────────────────────
    raw_story: str
    jira_id: str
    job_id: str
    domain: str
    iteration: int

    existing_ac: Optional[List[str]]

    # ── Trace / Timing ───────────────────────────────────────────────────
    trace: List[Any]
    timing: Optional[dict]

    # ── Analysis ─────────────────────────────────────────────────────────
    rule_score: Optional[float]
    rule_issues: Optional[List[str]]
    rule_suggestions: Optional[List[str]]

    nlp_score: Optional[float]
    nlp_issues: Optional[List[str]]
    nlp_suggestions: Optional[List[str]]

    llm_score: Optional[float]
    llm_issues: Optional[List[str]]
    llm_suggestions: Optional[List[str]]
    llm_failed: Optional[bool]

    final_score: Optional[float]
    initial_score: Optional[float]
    best_score: Optional[float]

    initial_story: Optional[str]

    # ── Flags ────────────────────────────────────────────────────────────
    is_reanalysis: Optional[bool]
    skip_reanalysis: Optional[bool]
    consecutive_llm_failures: Optional[int]
    refine_ac_only: Optional[bool]

    # ── Refinement ───────────────────────────────────────────────────────
    improved_story: Optional[str]
    acceptance_criteria: Optional[List[str]]

    # ── Rescore ──────────────────────────────────────────────────────────
    delta: Optional[float]
    score_after: Optional[float]
    previous_score: Optional[float]

    # ── Human Decision (post-pipeline) ───────────────────────────────────
    human_choice: Optional[Literal["approve", "reject_keep", "reject_relaunch"]]