from langgraph.graph import StateGraph, END

from .state import UserStoryState

from .nodes.analysis_node import analysis_node
from .nodes.refinement_node import refinement_node
from .nodes.evaluate_node import evaluate_node
from .edges import should_refine, should_retry


def build_graph():
    graph = StateGraph(UserStoryState)

    # =========================
    # NODES
    # =========================
    graph.add_node("analysis", analysis_node)
    graph.add_node("refinement", refinement_node)
    graph.add_node("evaluate", evaluate_node)

    graph.set_entry_point("analysis")

    # =========================
    # ANALYSIS → DECISION
    # =========================
    graph.add_conditional_edges(
        "analysis",
        should_refine,
        {
            "refine": "refinement",
            "skip": END, 
        }
    )

    # =========================
    # REFINE → EVALUATE
    # =========================
    graph.add_edge("refinement", "evaluate")

    # =========================
    # EVALUATE → DECISION
    # =========================
    graph.add_conditional_edges(
        "evaluate",
        should_retry,
        {
            "retry": "refinement",
            "alert": END,
            "end": END,
        }
    )

    return graph.compile()