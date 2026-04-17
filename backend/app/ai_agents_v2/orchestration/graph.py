# ============================================================
# ai_agents_v2/orchestration/graph.py (CORRIGÉ)
# ============================================================
"""
Orchestration Graph for Test Automation.

Coordinates the flow of:
1. Story Improvement Agent (ReAct with LangGraph)
2. (Future) Test Case Agent
3. (Future) Playwright Script Agent
"""

from datetime import datetime
from typing import Dict, Any
from langgraph.graph import StateGraph, END
import logging

from app.ai_agents_v2.user_story_refinement.agent import get_agent as get_story_agent
from app.ai_agents_v2.user_story_refinement.services.publishing_service import publishing_service
from app.ai_agents_v2.user_story_refinement.config import LLM_TEMPERATURE
from .checkpointer import checkpointer

from .state import (
    OrchestrationState,
    UserStoryImprovementResult,
    create_initial_state,
    mark_step_complete,
    mark_pipeline_complete,
    mark_failed
)

logger = logging.getLogger(__name__)


# ============================================================
# NODES
# ============================================================

async def story_improvement_node(state: OrchestrationState) -> OrchestrationState:
    """
    Story improvement node.
    
    ✅ Utilise directement le ReAct Agent (avec ChatOpenAI + LangGraph)
    ✅ Pas de couche llm_service intermédiaire
    """
    
    # ✅ Définir node_start au début de la fonction
    node_start = datetime.utcnow()
    
    try:
        # ✅ Récupérer les inputs
        original_story = state["original_story"]
        input_ac = state.get("input_acceptance_criteria", [])
        input_language = state.get("input_language", "en")
        jira_id = state["jira_id"]
        
        logger.info(f"[Node] Story Improvement")
        logger.info(f"  JIRA ID: {jira_id}")
        logger.info(f"  Language: {input_language}")
        logger.info(f"  Input AC: {len(input_ac)} items")
        
        agent = get_story_agent(temperature=LLM_TEMPERATURE)
        
        logger.info(f"[Agent] Running ReAct Agent for {jira_id}...")
        
        result = await agent.run(
            story=original_story,
            acceptance_criteria=input_ac,
            language=input_language,
            jira_id=jira_id
        )
        
        # ✅ Calculer la durée APRÈS l'exécution de l'agent
        node_end = datetime.utcnow()
        node_duration = (node_end - node_start).total_seconds()
        
        logger.info(f"  - Node duration: {node_duration:.2f}s")
        
        # ============================================================
        # Vérifier le résultat
        # ============================================================
        if result.get("error") or result.get("agent_status") == "error":
            error_msg = result.get("error") or "Unknown agent error"
            logger.error(f"Agent error: {error_msg}")
            return mark_failed(state, f"Agent failed: {error_msg}")
        
        # ============================================================
        # ✅ Mapper tous les champs du résultat de l'agent
        # ============================================================
        state["user_story_improvement"] = UserStoryImprovementResult(
            improved_story=result.get("improved_story", ""),
            acceptance_criteria=result.get("acceptance_criteria", []),
            score=result.get("score", 0.0),
            initial_score=result.get("initial_score", 0.0),
            final_score=result.get("final_score", 0.0),
            testability_score=result.get("testability_score", 0.0),
            is_testable=result.get("is_testable", False),
            testability_issues=result.get("testability_issues", []),
            testability_issues_fixed=result.get("testability_issues_fixed", []),
            is_improved=result.get("is_improved", False),
            valid=result.get("valid", False),
            language=result.get("language", "en"),
            language_consistent=result.get("language_consistent", False),
            role_preserved=result.get("role_preserved", False),
            original_actor=result.get("original_actor", ""),
            improved_actor=result.get("improved_actor", ""),
            similarity=result.get("similarity", 0.0),
            violations=result.get("violations", []),
            iterations=result.get("iterations", 0),
            agent_status=result.get("agent_status", "unknown"),
            error=result.get("error", None),
            duration_seconds=node_duration,
            model_used=result.get("model_used", "unknown"),
            prompt_tokens=result.get("prompt_tokens", 0),
            completion_tokens=result.get("completion_tokens", 0)
        )

        # ============================================================
        # Marquer comme complété
        # ============================================================
        state = mark_step_complete(state, "story_improvement_done")
        state["status"] = "success"
        
        logger.info(f"✓ Story improved successfully")
        logger.info(f"  - Score: {result.get('score', 0.0):.3f}")
        logger.info(f"  - Testability: {result.get('testability_score', 0.0):.3f}")
        logger.info(f"  - Iterations: {result.get('iterations', 0)}")
        logger.info(f"  - Duration: {node_duration:.2f}s")
        
        return state
    
    except Exception as e:
        logger.error(f"Story improvement failed: {e}", exc_info=True)
        return mark_failed(state, f"Story improvement: {str(e)}")


async def aggregator_node(state: OrchestrationState) -> OrchestrationState:
    """
    Node 2: Agrège les résultats finaux
    
    Combine tous les résultats disponibles et prépare la sortie finale.
    
    Actuellement: Agrège juste les résultats de story improvement
    Futur: Agrègera aussi Test Case, Playwright quand implémentés
    """
    
    logger.info(f"[Node] Aggregator: {state['jira_id']}")
    
    print(f"\n[📊 Node] Aggregator Starting")
    
    try:
        # ============================================================
        # Vérifier le statut
        # ============================================================
        if state["status"] == "failed":
            logger.error("Aggregation: Previous step failed")
            state["current_step"] = "done"
            print(f"[ERROR] Previous steps failed")
            return state
        
        # ============================================================
        # Marquer comme succès
        # ============================================================
        state["status"] = "success"
        state["current_step"] = "done"
        state["steps_completed"] = 1

        state = mark_pipeline_complete(state)
        
        # ============================================================
        # Event: Publishing Completed
        # ============================================================
        await publishing_service.publish_completed(state)
        
        # ✅ Afficher la durée depuis user_story_improvement
        duration = state.get("user_story_improvement", {}).get("duration_seconds", 0)
        logger.info(f"✓ Orchestration completed successfully (story improvement: {duration:.1f}s)")
        print(f"[✓] Orchestration completed successfully\n")
    
    except Exception as e:
        logger.error(f"Aggregation failed: {e}")
        state["errors"].append(f"Aggregation: {str(e)}")
        state["status"] = "failed"
        
        await publishing_service.publish_failed(state, str(e))
    
    return state


# ============================================================
# BUILD GRAPH
# ============================================================

def build_orchestration_graph():
    """
    Construit le graphe d'orchestration global.
    
    ✅ Architecture:
    - ReAct Agent gère lui-même la boucle tool-calling (via LangGraph)
    - ChatOpenAI supporte nativement les tools
    - Pas de wrapper LLM service inutile
    
    Flow (Actuel):
    Story Improvement → Aggregator → END
    
    Flow (Futur):
    Story Improvement → Test Case → Playwright → Aggregator → END
    
    Returns:
        Compiled LangGraph graph with checkpointer support
    """
    
    logger.info("Building orchestration graph...")
    
    graph = StateGraph(OrchestrationState)
    
    # ============================================================
    # Add Nodes
    # ============================================================
    graph.add_node("story_improvement", story_improvement_node)
    graph.add_node("aggregator", aggregator_node)
    
    logger.debug("✓ Nodes added: story_improvement, aggregator")
    
    # ============================================================
    # Add Edges (Flow)
    # ============================================================
    graph.add_edge("story_improvement", "aggregator")
    graph.add_edge("aggregator", END)
    
    logger.debug("✓ Edges added")
    
    # ============================================================
    # Set Entry Point
    # ============================================================
    graph.set_entry_point("story_improvement")
    
    logger.debug("✓ Entry point: story_improvement")
    
    # ============================================================
    # Compile Graph with Checkpointer
    # ============================================================
    compiled_graph = graph.compile(checkpointer=checkpointer)
    
    logger.info("✓ Orchestration graph built successfully")
    
    return compiled_graph