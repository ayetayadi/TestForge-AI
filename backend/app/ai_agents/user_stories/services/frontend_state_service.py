import json
from typing import Dict, Any

from app.core.redis_client import get_redis


class FrontendStateService:
    """
    Stocke l'état FINAL du job pour récupération frontend
    (ex: refresh page, fallback si SSE perdu)
    """

    PREFIX = "job_state"

    @staticmethod
    def _key(job_id: str) -> str:
        return f"{FrontendStateService.PREFIX}:{job_id}"

    # =========================================================
    # UPDATE FINAL STATE
    # =========================================================
    @staticmethod
    async def update(job_id: str, result: Dict[str, Any]) -> None:
        redis = get_redis()
    
        payload = {
            "status": FrontendStateService._compute_status(result),
            "phase": "completed",
    
            "result": {
                "job_id": job_id,
                "jira_id": result.get("jira_id"),
    
                "improved_story": result.get("improved_story"),
                "acceptance_criteria": result.get("acceptance_criteria"),
    
                "score_initial": result.get("initial_score", 0),
                "final_score": result.get("final_score", 0),
                "delta": (
                    result.get("final_score", 0)
                    - result.get("initial_score", 0)
                ),
    
                "iteration": result["iteration"],
            },
    
           "decision_status": "pending"
        }
    
        await redis.set(
            FrontendStateService._key(job_id),
            json.dumps(payload),
            ex=3600
        )
    # =========================================================
    # GET STATE (fallback frontend)
    # =========================================================
    @staticmethod
    async def get(job_id: str) -> Dict[str, Any] | None:
        redis = get_redis()

        data = await redis.get(FrontendStateService._key(job_id))

        if not data:
            return None

        return json.loads(data)

    # =========================================================
    # STATUS
    # =========================================================
    @staticmethod
    def _compute_status(result: Dict[str, Any]) -> str:
        if result.get("guard_failed"):
            return "failed"
        return "completed"