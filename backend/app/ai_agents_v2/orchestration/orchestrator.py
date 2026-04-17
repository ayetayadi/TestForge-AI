# ============================================================
# ai_agents_v2/orchestration/orchestrator.py (CORRIGÉ)
# ============================================================
"""
Orchestrator for Test Automation with ReAct Agent.
"""

from datetime import datetime
from typing import Dict, Any, Optional
import logging

from app.ai_agents_v2.user_story_refinement.services.publishing_service import publishing_service
from .graph import build_orchestration_graph
from .state import OrchestrationState

logger = logging.getLogger(__name__)


class TestAutomationOrchestrator:
    """
    Orchestrateur principal pour l'automatisation de test.
    
    ✅ Coordonne:
    - Story Improvement Agent (ReAct avec ChatOpenAI + LangGraph)
    - Checkpointing pour resume
    - SSE publishing
    """
    
    def __init__(self):
        """Initialize the orchestrator"""
        logger.info("Initializing TestAutomationOrchestrator...")
        self.graph = build_orchestration_graph()
        logger.info("✓ TestAutomationOrchestrator initialized")
    
    async def run(
        self,
        jira_id: str,
        story: str,
        thread_id: Optional[str] = None,
        acceptance_criteria: Optional[list] = None,
        language: str = "en"
    ) -> Dict[str, Any]:
        """
        Execute the orchestrator.
        
        ⭐ Appelle graph.ainvoke() pour exécuter le pipeline
        
        Args:
            jira_id: Jira issue ID
            story: User story text
            thread_id: Thread ID for checkpointing (optional)
            acceptance_criteria: Existing ACs (optional)
            language: Story language (default: "en")
            
        Returns:
            Result dict with story improvement results
        """
        
        # ============================================================
        # SETUP
        # ============================================================
        if not thread_id:
            thread_id = f"{jira_id}-{datetime.now().timestamp()}"
        
        config = {"configurable": {"thread_id": thread_id}}
        
        logger.info(f"Orchestrator running: {jira_id} (thread: {thread_id})")
        
        print(f"\n{'='*80}")
        print(f"[🎯 ORCHESTRATOR] Test Automation Pipeline")
        print(f"{'='*80}")
        print(f"[INFO] Jira ID: {jira_id}")
        print(f"[INFO] Thread ID: {thread_id}")
        print(f"[INFO] Language: {language}")
        print(f"{'='*80}\n")
        
        try:
            # ============================================================
            # Create Initial State
            # ============================================================
            # ✅ Utiliser create_initial_state au lieu de construire manuellement
            from .state import create_initial_state
            
            initial_state = create_initial_state(
                jira_id=jira_id,
                version_id=thread_id,
                story=story,
                acceptance_criteria=acceptance_criteria,
                language=language,
            )
            
            # Ajouter les champs supplémentaires
            
            logger.debug(f"Initial state created: {thread_id}")
            
            # ============================================================
            # SSE EVENT: Processing Started
            # ============================================================
            await publishing_service.publish_processing(
                state=initial_state,
                message="Orchestration started - Story Improvement Agent initializing...",
                details={
                    "jira_id": jira_id,
                    "thread_id": thread_id,
                    "language": language
                }
            )
            
            # ============================================================
            # ⭐ INVOKE GRAPH ⭐
            # ============================================================
            logger.info("Running orchestration graph...")
            
            final_state = await self.graph.ainvoke(
                input=initial_state,
                config=config
            )

            if final_state.get("status") == "failed":
                logger.error(f"Graph execution failed: {final_state.get('errors', [])}")
                
            logger.info(f"Graph execution completed: {final_state['status']}")
            
            # ============================================================
            # Format Output
            # ============================================================
            output = self._format_output(final_state)
            output["thread_id"] = thread_id
            
            # ============================================================
            # SSE EVENT: Completed
            # ============================================================
            await publishing_service.publish_completed(final_state)
            
            # ============================================================
            # Print Summary
            # ============================================================
            # ✅ Récupérer la durée depuis user_story_improvement
            improvement = final_state.get("user_story_improvement", {})
            duration = improvement.get("duration_seconds", 0.0)
            
            print(f"\n{'='*80}")
            print(f"[✅ COMPLETE] Status: {final_state['status'].upper()}")
            print(f"[INFO] Steps Completed: {final_state['steps_completed']}")
            print(f"[INFO] Duration: {duration:.1f}s")
            if final_state.get("errors"):
                print(f"[⚠️  WARNINGS] {len(final_state['errors'])} errors")
                for error in final_state["errors"]:
                    print(f"  - {error}")
            print(f"{'='*80}\n")
            
            logger.info(f"Orchestrator completed successfully")
            
            return output
        
        except Exception as e:
            logger.error(f"Orchestrator failed: {e}", exc_info=True)
            
            # ============================================================
            # SSE EVENT: Failed
            # ============================================================
            error_state = {
                "jira_id": jira_id,
                "version_id": thread_id,
                "timestamp": datetime.now().isoformat(),
                "errors": [str(e)],
                "status": "failed"
            }
            
            await publishing_service.publish_failed(error_state, str(e))
            
            # ============================================================
            # Print Error
            # ============================================================
            print(f"\n{'='*80}")
            print(f"[❌ FAILED] Orchestrator Error")
            print(f"[ERROR] {e}")
            print(f"{'='*80}\n")
            
            return {
                "jira_id": jira_id,
                "version_id": thread_id,
                "thread_id": thread_id,
                "timestamp": datetime.now().isoformat(),
                "status": "failed",
                "error": str(e),
                "steps_completed": 0,
            }
    
    async def resume(self, thread_id: str) -> Dict[str, Any]:
        """
        Resume a previously interrupted version user story.
        
        ⭐ Reprend depuis le dernier checkpoint
        
        Args:
            thread_id: Thread ID of the version to resume
            
        Returns:
            Result dict
        """
        
        config = {"configurable": {"thread_id": thread_id}}
        
        logger.info(f"Resuming orchestration: {thread_id}")
        
        print(f"\n{'='*80}")
        print(f"[🔄 RESUMING] Previously Interrupted Version")
        print(f"[INFO] Thread ID: {thread_id}")
        print(f"{'='*80}\n")
        
        try:
            # ============================================================
            # ⭐ INVOKE GRAPH WITH RESUME ⭐
            # ============================================================
            logger.info(f"Resuming from checkpoint: {thread_id}")
            
            final_state = await self.graph.ainvoke(
                input=None,  # None = reprendre depuis checkpoint
                config=config
            )
            
            logger.info(f"Version resumed successfully: {final_state['status']}")
            
            output = self._format_output(final_state)
            output["version_id"] = thread_id
            output["resumed"] = True
            
            print(f"\n{'='*80}")
            print(f"[✅ RESUMED] Version completed")
            print(f"[INFO] Status: {final_state['status'].upper()}")
            print(f"{'='*80}\n")
            
            return output
        
        except Exception as e:
            logger.error(f"Resume failed: {e}", exc_info=True)
            
            print(f"\n{'='*80}")
            print(f"[❌ RESUME FAILED]")
            print(f"[ERROR] {e}")
            print(f"{'='*80}\n")
            
            return {
                "thread_id": thread_id,
                "status": "failed",
                "error": str(e),
                "resumed": True,
            }
    
    def _format_output(self, state: OrchestrationState) -> Dict[str, Any]:
        """
        Format la sortie finale.
        
        ✅ Inclut tous les champs de UserStoryImprovementResult
        ✅ Gère dict ET dataclass/TypedDict
        """
        
        output = {
            "jira_id": state.get("jira_id"),
            "version_id": state.get("version_id"),
            "timestamp": state.get("timestamp"),
            "status": state["status"],
            "steps_completed": state["steps_completed"],
            "errors": state.get("errors", []),
            "model_used": state.get("user_story_improvement", {}).get("model_used", "unknown") if state.get("user_story_improvement") else "unknown",
            "prompt_tokens": state.get("user_story_improvement", {}).get("prompt_tokens", 0) if state.get("user_story_improvement") else 0,
            "completion_tokens": state.get("user_story_improvement", {}).get("completion_tokens", 0) if state.get("user_story_improvement") else 0,
            # ✅ duration_seconds SUPPRIMÉ (pas dans OrchestrationState)
        }
        
        if state.get("user_story_improvement"):
            improvement = state["user_story_improvement"]
            
            # ✅ Gérer dict ET dataclass/TypedDict
            if isinstance(improvement, dict):
                improved_data = improvement
            else:
                # Si c'est une dataclass, convertir en dict
                improved_data = (
                    improvement.__dict__ 
                    if hasattr(improvement, '__dict__') 
                    else dict(improvement)
                )
            
            # ✅ INCLURE TOUS LES CHAMPS
            output["user_story_improvement"] = {
                "improved_story": improved_data.get("improved_story", ""),
                "acceptance_criteria": improved_data.get("acceptance_criteria", []),
                "score": improved_data.get("score", 0.0),
                "initial_score": improved_data.get("initial_score", 0.0),
                "final_score": improved_data.get("final_score", 0.0),
                "testability_score": improved_data.get("testability_score", 0.0),
                "is_testable": improved_data.get("is_testable", False),
                "testability_issues": improved_data.get("testability_issues", []),
                "testability_issues_fixed": improved_data.get("testability_issues_fixed", []),
                "is_improved": improved_data.get("is_improved", False),
                "valid": improved_data.get("valid", False),
                "language": improved_data.get("language", ""),
                "language_consistent": improved_data.get("language_consistent", False),
                "role_preserved": improved_data.get("role_preserved", False),
                "original_actor": improved_data.get("original_actor", ""),
                "improved_actor": improved_data.get("improved_actor", ""),
                "similarity": improved_data.get("similarity", 0.0),
                "violations": improved_data.get("violations", []),
                "iterations": improved_data.get("iterations", 0),
                "agent_status": improved_data.get("agent_status", "unknown"),
                "duration_seconds": improved_data.get("duration_seconds", 0.0),  # ✅ ICI SEULEMENT
            }
        
        return output