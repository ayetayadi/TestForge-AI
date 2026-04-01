from langgraph.graph import StateGraph, END
from .state import UserStoryState
from .edge import should_refine, should_retry
from .nodes.rescore import rescore_node
from .nodes.prepare_skip import prepare_skip_node
from app.ai.agents.user_story.analysis.nodes import analysis_node
from app.ai.agents.user_story.refinement.nodes import refinement_node


def build_graph():
    g = StateGraph(UserStoryState)

    # =========================
    # NODES
    # =========================
    g.add_node("analysis", analysis_node)

    async def refinement_with_flag(state: dict) -> dict:
        jira_id = state.get("jira_id", "?")
    
        state["is_reanalysis"] = False
        state["llm_issues"] = []
        state["llm_suggestions"] = []
    
        state = await refinement_node(state)
    
        if state.get("llm_failed"):
            state["consecutive_llm_failures"] = state.get("consecutive_llm_failures", 0) + 1
            print(f"[{jira_id}] [GRAPH] LLM failed (consecutive={state['consecutive_llm_failures']})")
            state["skip_reanalysis"] = True
        else:
            state["consecutive_llm_failures"] = 0
            state["is_reanalysis"] = True
    
        return state
    
    g.add_node("refinement", refinement_with_flag)

    async def reanalysis_with_tracking(state: dict) -> dict:
        state = await analysis_node(state)

        jira_id = state.get("jira_id", "?")

        if state.get("llm_failed"):
            state["consecutive_llm_failures"] = state.get("consecutive_llm_failures", 0) + 1
            print(f"[{jira_id}] [GRAPH] LLM failed in reanalysis (consecutive={state['consecutive_llm_failures']})")
        else:
            state["consecutive_llm_failures"] = 0

        return state

    g.add_node("reanalysis", reanalysis_with_tracking)
    g.add_node("rescore", rescore_node)
    g.add_node("prepare_skip", prepare_skip_node)

    # =========================
    # ENTRY → always analysis
    # =========================
    g.set_entry_point("analysis")

    # =========================
    # ANALYSIS → REFINE / SKIP
    # =========================
    g.add_conditional_edges(
        "analysis",
        should_refine,
        {
            "refine": "refinement",
            "skip_to_human": "prepare_skip",
        },
    )

    # =========================
    # PREPARE_SKIP → REFINE or END
    # =========================
    g.add_conditional_edges(
        "prepare_skip",
        lambda state: "refine" if not state.get("skip_reanalysis") else "end",
        {
            "refine": "refinement",
            "end": "rescore",
        },
    )

    # =========================
    # REFINEMENT → REANALYSIS or RESCORE
    # =========================
    g.add_conditional_edges(
        "refinement",
        lambda state: "rescore" if state.get("skip_reanalysis") else "reanalysis",
        {
            "reanalysis": "reanalysis",
            "rescore": "rescore",
        },
    )

    # =========================
    # REANALYSIS → RESCORE (always)
    # =========================
    g.add_edge("reanalysis", "rescore")

    # =========================
    # RESCORE → RETRY or END
    # =========================
    g.add_conditional_edges(
        "rescore",
        should_retry,
        {
            "end": END,
            "retry": "refinement",
            "alert": END,
        },
    )

    return g.compile()