import json
import logging
from datetime import datetime
from typing import Optional

from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)


class FrontendStateService:
    """Gestion de l'état UI (SSE + cache Redis léger)"""

    KEY_PREFIX = "ui:job:"
    TTL = 3600  # 1 heure

    @classmethod
    async def update(cls, job_id: str, state: dict) -> None:
        if not job_id:
            return

        ui_state = {
            "job_id": job_id,
            "jira_id": state.get("jira_id"),
            "phase": state.get("ui_phase"),
            "iteration": state.get("iteration", 0),
            "score": cls._safe_float(state.get("final_score")),
            "score_before": cls._safe_float(
                state.get("initial_score") or state.get("previous_score")
            ),
            "score_after": cls._safe_float(
                state.get("final_score") or state.get("score_after")
            ),
            "delta": cls._safe_float(state.get("delta")),
            "outcome": state.get("outcome"),
            "error": state.get("error"),
            "updated_at": datetime.utcnow().isoformat(),
        }

        redis = get_redis()
        key = f"{cls.KEY_PREFIX}{job_id}"

        try:
            await redis.setex(key, cls.TTL, json.dumps(ui_state))
            logger.debug(f"[UI] Updated {job_id}: {ui_state['phase']}")
        except Exception as e:
            logger.error(f"[UI] Redis error {job_id}: {e}")

        try:
            from app.streaming.sse_manager import publish_event
            publish_event(job_id, "ui_update", ui_state)
        except Exception as e:
            logger.error(f"[UI] SSE error {job_id}: {e}")

    @classmethod
    async def get(cls, job_id: str) -> Optional[dict]:
        try:
            redis = get_redis()
            key = f"{cls.KEY_PREFIX}{job_id}"

            data = await redis.get(key)
            return json.loads(data) if data else None

        except Exception as e:
            logger.error(f"[UI] Get error {job_id}: {e}")
            return None

    @staticmethod
    def _safe_float(value) -> float:
        if value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0