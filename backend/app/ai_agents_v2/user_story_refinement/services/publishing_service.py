# ============================================================
# app/services/publishing_service.py
# ============================================================
from typing import Dict, Any, Optional
import time
from app.utils.pipeline_utils import safe_publish


class PublishingService:
    """
    Service pour publier les événements SSE.
    
    Pour ReAct Agent:
    - "processing": Agent en cours d'exécution
    - "completed": Terminé avec succès
    - "failed": Erreur
    """
    
    ALLOWED_PHASES = {
        "processing",      # ReAct Agent tourne
        "completed",       # Succès
        "failed"           # Erreur
    }
    
    @staticmethod
    def _safe_emit(state: Dict[str, Any], event: str, data: Dict[str, Any]) -> None:
        """
        Publie un événement SSE de manière sécurisée.
        
        Args:
            state: État de l'orchestration
            event: Type d'événement
            data: Données de l'événement
        """
        try:
            safe_publish(state, event, data)
        except Exception as e:
            print(f"[PUBLISH ERROR] {event} → {e}")
    
    # ============================================================
    # PROCESSING (Agent en cours)
    # ============================================================
    @staticmethod
    async def publish_processing(
        state: Dict[str, Any],
        message: str = "Processing...",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Publie que l'agent est en cours d'exécution.
        
        Args:
            state: État de l'orchestration
            message: Message pour l'utilisateur
            details: Détails supplémentaires
        """
        
        PublishingService._safe_emit(
            state,
            "processing",
            {
                "status": "processing",
                "message": message,
                "step": state.get("current_step", "unknown"),
                "details": details or {}
            }
        )
    
    # ============================================================
    # COMPLETED (Succès)
    # ============================================================
    @staticmethod
    async def publish_completed(state: Dict[str, Any]) -> None:
        """
        Publie la complétion succès de l'orchestration.
        
        Args:
            state: État final de l'orchestration
        """
        
        PublishingService._safe_emit(
            state,
            "completed",
            {
                "status": "completed",
                "message": "Orchestration completed successfully",
                "jira_id": state.get("jira_id"),
                "job_id": state.get("job_id"),
                "steps_completed": state.get("steps_completed", 0),
                "user_story_improvement": state.get("user_story_improvement", {}),
            }
        )
    
    # ============================================================
    # FAILED (Erreur)
    # ============================================================
    @staticmethod
    async def publish_failed(state: Dict[str, Any], error: Optional[str] = None) -> None:
        """
        Publie une erreur d'exécution.
        
        Args:
            state: État de l'orchestration
            error: Message d'erreur
        """
        
        PublishingService._safe_emit(
            state,
            "failed",
            {
                "status": "failed",
                "message": error or "Orchestration failed",
                "jira_id": state.get("jira_id"),
                "job_id": state.get("job_id"),
                "errors": state.get("errors", []),
                "error": error
            }
        )
    
    # ============================================================
    # EVENT LOG (Optionnel - pour audit)
    # ============================================================
    @staticmethod
    def add_event(
        state: Dict[str, Any],
        step: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Ajoute un événement au log (pour audit/debugging).
        
        Args:
            state: État de l'orchestration
            step: Nom de l'étape
            metadata: Métadonnées supplémentaires
        """
        
        state.setdefault("events", [])
        
        state["events"].append({
            "step": step,
            "timestamp": time.time(),
            **(metadata or {})
        })


# Singleton
publishing_service = PublishingService()