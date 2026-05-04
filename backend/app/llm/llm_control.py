import asyncio
import logging
import os
import time
from contextvars import ContextVar
from typing import Any
from langchain_groq import ChatGroq
from groq import RateLimitError
from app.core.config import settings
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# Semaphore: max 5 appels LLM simultanés (1 par clé)
llm_semaphore = asyncio.Semaphore(5)

_MIN_CALL_INTERVAL = 10.0  # seconds between calls on the SAME key
_last_call_times: dict[str, float] = {}  # per-key throttle — keys run independently

_RETRY_DELAYS = [15, 30, 60]
_MAX_RETRY_WAIT = 120.0

# ──────────────────────────────────────────────────────────────
# POOL DE CLÉS (chargé une fois au démarrage)
# ──────────────────────────────────────────────────────────────
_API_KEYS = [
    os.getenv("GROQ_API_KEY_1", ""),
    os.getenv("GROQ_API_KEY_2", ""),
    os.getenv("GROQ_API_KEY_3", ""),
    os.getenv("GROQ_API_KEY_4", ""),
    os.getenv("GROQ_API_KEY_5", ""),
]

print("=" * 60)
print("🔍 DEBUG API KEYS:")
for i in range(1, 6):
    key = os.getenv(f"GROQ_API_KEY_{i}", "")
    print(f"  GROQ_API_KEY_{i} = '{key[:10]}...' (len={len(key)})" if key else f"  GROQ_API_KEY_{i} = NOT FOUND")
print("=" * 60)

_API_KEYS = [k for k in _API_KEYS if k and len(k) > 10]
if not _API_KEYS:
    fallback = settings.GROQ_API_KEY_1 or ""
    if fallback:
        _API_KEYS = [fallback]

logger.info(f"[LLM KEY] Loaded {len(_API_KEYS)} Groq API key(s): {[k[:12]+'...' for k in _API_KEYS]}")

# Index pour la rotation de fallback (appels hors-worker)
_current_key_index = 0


def _get_next_api_key() -> str:
    """Rotation circulaire — utilisée uniquement en fallback (appels hors-worker)."""
    global _current_key_index
    if not _API_KEYS:
        return settings.GROQ_API_KEY_1 or ""
    key = _API_KEYS[_current_key_index]
    _current_key_index = (_current_key_index + 1) % len(_API_KEYS)
    logger.info(f"[LLM KEY] 🔄 Fallback rotation → key [{_current_key_index}/{len(_API_KEYS)}]: {key[:12]}...")
    return key


# ──────────────────────────────────────────────────────────────
# CLÉ PAR WORKER — ContextVar (isolé par tâche asyncio)
# ──────────────────────────────────────────────────────────────
_worker_api_key: ContextVar[str | None] = ContextVar("worker_api_key", default=None)


def set_worker_api_key(key: str) -> None:
    """
    Assigne une clé dédiée à la tâche asyncio courante.
    Doit être appelé au démarrage de chaque worker, avant tout appel LLM.
    Le ContextVar est isolé par tâche — aucun risque d'écrasement entre workers.
    """
    _worker_api_key.set(key)
    logger.info(f"[LLM KEY] ✅ Worker key set for this task: {key[:12]}...")


def get_worker_api_key() -> str | None:
    """Retourne la clé assignée à la tâche courante, ou None."""
    return _worker_api_key.get()


# ──────────────────────────────────────────────────────────────
# LLM CONTROLÉ
# ──────────────────────────────────────────────────────────────

class ControlledChatGroq(ChatGroq):
    """
    ChatGroq avec sémaphore global, pacing inter-appels et retry rate-limit.
    Chaque instance utilise la clé fixée à sa création (issue du ContextVar du worker).
    Pas de rotation globale : chaque worker garde sa clé dédiée.
    """

    async def _agenerate(self, *args, **kwargs) -> Any:
        key_id = str(self.groq_api_key) if self.groq_api_key else "NO_KEY"
        key_preview = key_id[:12] + "..."

        async with llm_semaphore:
            last_call = _last_call_times.get(key_id, 0.0)
            elapsed = time.monotonic() - last_call
            if elapsed < _MIN_CALL_INTERVAL:
                wait_time = _MIN_CALL_INTERVAL - elapsed
                logger.debug(f"[LLM KEY] ⏳ Pacing key {key_preview}: waiting {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)

            for attempt in range(len(_RETRY_DELAYS) + 1):
                try:
                    logger.info(f"[LLM KEY] 🚀 Calling Groq with key: {key_preview} (attempt {attempt + 1})")
                    _last_call_times[key_id] = time.monotonic()
                    result = await super()._agenerate(*args, **kwargs)
                    logger.info(f"[LLM KEY] ✅ Success with key: {key_preview}")
                    return result

                except RateLimitError as exc:
                    should_retry, wait = _parse_rate_limit(exc, attempt)

                    if not should_retry or attempt == len(_RETRY_DELAYS):
                        logger.error(f"[LLM KEY] ❌ Rate limit exhausted for key: {key_preview}")
                        raise

                    logger.warning(
                        f"[LLM KEY] ⏳ Rate limited on key: {key_preview} — retrying in {wait}s "
                        f"(attempt {attempt + 1}/{len(_RETRY_DELAYS)})"
                    )
                    await asyncio.sleep(wait)

                except Exception as exc:
                    logger.error(f"[LLM ERROR] Groq call failed with key {key_preview}: {exc}")
                    raise


def _parse_rate_limit(exc: RateLimitError, attempt: int) -> tuple[bool, float]:
    try:
        response = getattr(exc, "response", None)
        if response is not None:
            headers = response.headers

            if headers.get("x-should-retry", "").lower() == "false":
                retry_after = _read_retry_after(headers)
                logger.warning(f"[LLM KEY] Groq says do not retry (retry-after={retry_after}s)")
                return False, retry_after or 0.0

            retry_after = _read_retry_after(headers)
            if retry_after is not None:
                if retry_after > _MAX_RETRY_WAIT:
                    logger.warning(f"[LLM KEY] retry-after={retry_after}s > {_MAX_RETRY_WAIT}s")
                    return False, retry_after
                return True, retry_after
    except Exception:
        pass
    return True, _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]


def _read_retry_after(headers) -> float | None:
    for header in ("retry-after", "x-ratelimit-reset-requests"):
        val = headers.get(header)
        if val:
            try:
                return float(val)
            except ValueError:
                pass
    return None


def create_llm(temperature: float, model: str, max_tokens: int) -> ControlledChatGroq:
    """
    Crée un LLM avec la clé dédiée au worker courant (via ContextVar).
    Si aucune clé de worker n'est définie (appel hors-worker), utilise la rotation globale.
    """
    key = _worker_api_key.get()
    if key:
        logger.info(f"[LLM KEY] create_llm → using worker key: {key[:12]}...")
    else:
        key = _get_next_api_key()
        logger.info(f"[LLM KEY] create_llm → no worker key, using fallback rotation: {key[:12]}...")

    return ControlledChatGroq(
        groq_api_key=key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
