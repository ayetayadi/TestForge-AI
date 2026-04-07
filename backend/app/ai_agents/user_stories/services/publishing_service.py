from typing import Dict, Any, Optional
import time
from app.utils.pipeline_utils import safe_publish


class PublishingService:

    ALLOWED_PHASES = {
        "analyzing",
        "refining",
        "evaluating",
        "completed",
        "failed"
    }

    @staticmethod
    def _safe_emit(state: Dict[str, Any], event: str, data: Dict[str, Any]) -> None:
        try:
            safe_publish(state, event, data)
        except Exception as e:
            print(f"[PUBLISH ERROR] {event} → {e}")

    # =========================
    # PHASE UPDATE (SSE ONLY)
    # =========================
    @staticmethod
    async def publish_phase(state: Dict[str, Any], phase: str) -> None:
        if phase not in PublishingService.ALLOWED_PHASES:
            return

        iteration = state.get("iteration", 0)

        PublishingService._safe_emit(
            state,
            phase,
            {
                "phase": phase,
                "iteration": iteration
            }
        )

    # =========================
    # COMPLETED
    # =========================
    @staticmethod
    async def publish_completed(state: Dict[str, Any]) -> None:
        PublishingService._safe_emit(
            state,
            "completed",
            {
                "iteration": state.get("iteration"),
                "final_score": state.get("final_score"),
                "improved_story": state.get("improved_story"),
                "acceptance_criteria": state.get("acceptance_criteria"),
            }
        )

    # =========================
    # FAILED
    # =========================
    @staticmethod
    async def publish_failed(state: Dict[str, Any]) -> None:
        PublishingService._safe_emit(
            state,
            "failed",
            {
                "error": state.get("error"),
                "iteration": state.get("iteration", 0)
            }
        )

    # =========================
    # EVENTS
    # =========================
    @staticmethod
    def add_event(
        state: Dict[str, Any],
        step: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        state.setdefault("events", [])

        state["events"].append({
            "step": step,
            "iteration": state.get("iteration", 0),
            "timestamp": time.time(),
            **(metadata or {})
        })


publishing_service = PublishingService()