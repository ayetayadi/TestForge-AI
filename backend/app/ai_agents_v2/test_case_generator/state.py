from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class TestCaseAgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]

    user_story: str
    acceptance_criteria: List[str]
    model: str

    # Phase 1 — story analysis output
    analysis_result: Optional[Dict[str, Any]]

    # Phase 2/4 — current working set of test cases (updated by draft/refine/save)
    test_cases_structured: Optional[List[Dict[str, Any]]]
    user_story_analysis: Optional[Dict[str, Any]]

    # Phase 3 — critique feedback
    critique_result: Optional[Dict[str, Any]]

    # Refinement iteration counter (prevents infinite loops)
    iteration_count: int

    # Terminal flags
    approved: bool
    flagged_for_human: bool
    saved_paths: Optional[Dict[str, str]]

    # Execution trace
    thought_action_log: List[Dict[str, Any]]
