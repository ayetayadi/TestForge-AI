# import asyncio
# import logging
# import os
# import time
# from typing import Any
# from langchain_groq import ChatGroq
# from groq import RateLimitError
# from app.core.config import settings
# from dotenv import load_dotenv
# load_dotenv()

# logger = logging.getLogger(__name__)


# llm_semaphore = asyncio.Semaphore(5)

# # Minimum gap between consecutive API calls
# _MIN_CALL_INTERVAL = 5.0  # seconds
# _last_call_time: float = 0.0

# # Retry delays (seconds) when Groq returns 429
# _RETRY_DELAYS = [30, 60, 120, 180]

# # If Groq says retry-after > this threshold, fail immediately
# _MAX_RETRY_WAIT = 300.0

# # ✅ Rotation des clés API (une par compte Groq gratuit)
# _API_KEYS = [
#     os.getenv("GROQ_API_KEY_1", ""),
#     os.getenv("GROQ_API_KEY_2", ""),
#     os.getenv("GROQ_API_KEY_3", ""),
#     os.getenv("GROQ_API_KEY_4", ""),
#     os.getenv("GROQ_API_KEY_5", ""),
# ]
# # 🔍 DEBUG - Afficher ce qui est chargé
# print("=" * 60)
# print("🔍 DEBUG API KEYS:")
# print(f"  GROQ_API_KEY_1 = '{os.getenv('GROQ_API_KEY_1', 'NOT FOUND')[:5]}...'")
# print(f"  GROQ_API_KEY_2 = '{os.getenv('GROQ_API_KEY_2', 'NOT FOUND')[:5]}...'")
# print(f"  GROQ_API_KEY_3 = '{os.getenv('GROQ_API_KEY_3', 'NOT FOUND')[:5]}...'")
# print(f"  GROQ_API_KEY_4 = '{os.getenv('GROQ_API_KEY_4', 'NOT FOUND')[:5]}...'")
# print(f"  GROQ_API_KEY_5 = '{os.getenv('GROQ_API_KEY_5', 'NOT FOUND')[:5]}...'")
# print(f"  _API_KEYS count: {len(_API_KEYS)}")

# for i, k in enumerate(_API_KEYS):
#     print(f"  Key {i+1}: {k[:15]}... (len={len(k)})")
# print("=" * 60)
# # Filtrer les clés vides + ajouter la clé par défaut si aucune
# _API_KEYS = [k for k in _API_KEYS if k]
# if not _API_KEYS:
#     _API_KEYS = [settings.GROQ_API_KEY_1 or ""]
#     _API_KEYS = [k for k in _API_KEYS if k]

# # 🔍 LOG au démarrage
# logger.info(f"[LLM KEY] Loaded {len(_API_KEYS)} API key(s): {[k[:12]+'...' for k in _API_KEYS]}")

# _current_key_index = 0


# def _get_next_api_key() -> str:
#     """Rotation circulaire des clés API."""
#     global _current_key_index
#     if not _API_KEYS:
#         return settings.GROQ_API_KEY_1 or ""
#     key = _API_KEYS[_current_key_index]
#     _current_key_index = (_current_key_index + 1) % len(_API_KEYS)
    
#     # 🔍 LOG de rotation
#     key_preview = key[:12] + "..." if key else "NO_KEY"
#     logger.info(f"[LLM KEY] 🔄 Rotation → using key [{_current_key_index}/{len(_API_KEYS)}]: {key_preview}")
    
#     return key


# class ControlledChatGroq(ChatGroq):
#     """ChatGroq with global serialization, inter-call pacing, rate-limit retry, and API key rotation."""

#     async def _agenerate(self, *args, **kwargs) -> Any:
#         global _last_call_time

#         async with llm_semaphore:
#             # Pace: enforce a minimum gap since the last API call
#             elapsed = time.monotonic() - _last_call_time
#             if elapsed < _MIN_CALL_INTERVAL:
#                 await asyncio.sleep(_MIN_CALL_INTERVAL - elapsed)

#             for attempt in range(len(_RETRY_DELAYS) + 1):
#                 try:
#                     # ✅ Rotation de clé API à chaque tentative
#                     self.groq_api_key = _get_next_api_key()
                    
#                     # 🔍 LOG
#                     key_preview = self.groq_api_key[:12] + "..." if self.groq_api_key else "NO_KEY"
#                     logger.info(f"[LLM KEY] 🚀 Calling Groq with key: {key_preview} (attempt {attempt + 1})")
                    
#                     _last_call_time = time.monotonic()
#                     result = await super()._agenerate(*args, **kwargs)
#                     logger.debug("[LLM] Response received from Groq")
                    
#                     # 🔍 LOG succès
#                     logger.info(f"[LLM KEY] ✅ Success with key: {key_preview}")
#                     return result

#                 except RateLimitError as exc:
#                     key_preview = self.groq_api_key[:12] + "..." if self.groq_api_key else "NO_KEY"
#                     should_retry, wait = _parse_rate_limit(exc, attempt)
                    
#                     if not should_retry:
#                         # ✅ Si quota épuisé sur cette clé, essayer la suivante
#                         if len(_API_KEYS) > 1:
#                             logger.warning(
#                                 f"[LLM KEY] ⚠️ Rate limited on key: {key_preview} "
#                                 f"(retry-after={wait}s) — switching to next key..."
#                             )
#                             await asyncio.sleep(5)  # Petite pause
#                             continue  # ← Réessaie avec la clé suivante
#                         logger.error(
#                             f"[LLM KEY] ❌ Rate limit — no more API keys available. Failing job."
#                         )
#                         raise
#                     if attempt == len(_RETRY_DELAYS):
#                         logger.error(f"[LLM KEY] ❌ Rate limit exceeded after {len(_RETRY_DELAYS)} retries")
#                         raise
#                     logger.warning(
#                         f"[LLM KEY] ⏳ Rate limited on key: {key_preview} — retrying in {wait}s "
#                         f"(attempt {attempt + 1}/{len(_RETRY_DELAYS)})"
#                     )
#                     await asyncio.sleep(wait)

#                 except Exception as exc:
#                     key_preview = self.groq_api_key[:12] + "..." if self.groq_api_key else "NO_KEY"
#                     logger.error(f"[LLM ERROR] Groq call failed with key {key_preview}: {exc}")
#                     raise


# def _parse_rate_limit(exc: RateLimitError, attempt: int) -> tuple[bool, float]:
#     """
#     Returns (should_retry, wait_seconds).
#     Fails immediately (should_retry=False) when:
#     - Groq sets x-should-retry: false, OR
#     - retry-after exceeds _MAX_RETRY_WAIT (daily quota exhausted)
#     """
#     try:
#         response = getattr(exc, "response", None)
#         if response is not None:
#             headers = response.headers

#             if headers.get("x-should-retry", "").lower() == "false":
#                 retry_after = _read_retry_after(headers)
#                 # 🔍 LOG
#                 logger.warning(f"[LLM KEY] Groq says do not retry (retry-after={retry_after}s)")
#                 return False, retry_after or 0.0

#             retry_after = _read_retry_after(headers)
#             if retry_after is not None:
#                 if retry_after > _MAX_RETRY_WAIT:
#                     # 🔍 LOG
#                     logger.warning(
#                         f"[LLM KEY] retry-after={retry_after}s > {_MAX_RETRY_WAIT}s threshold "
#                         f"— daily quota likely exhausted"
#                     )
#                     return False, retry_after
#                 return True, retry_after
#     except Exception:
#         pass
#     return True, _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]


# def _read_retry_after(headers) -> float | None:
#     for header in ("retry-after", "x-ratelimit-reset-requests"):
#         val = headers.get(header)
#         if val:
#             try:
#                 return float(val)
#             except ValueError:
#                 pass
#     return None


# def create_llm(temperature: float, model: str, max_tokens: int) -> ControlledChatGroq:
#     return ControlledChatGroq(
#         groq_api_key=_API_KEYS[0] if _API_KEYS else (settings.GROQ_API_KEY_1 or ""),
#         model=model,
#         temperature=temperature,
#         max_tokens=max_tokens,
#     )


import asyncio
import logging
import os
import time
from typing import Any
from langchain_openai import ChatOpenAI 
from openai import RateLimitError
from app.core.config import settings
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# Serialize all outgoing LLM calls
llm_semaphore = asyncio.Semaphore(5)

# Minimum gap between consecutive API calls
_MIN_CALL_INTERVAL = 3.0  # secondes (OpenRouter est plus rapide)
_last_call_time: float = 0.0

# Retry delays
_RETRY_DELAYS = [10, 20, 40, 80]

# If retry-after > this, switch key
_MAX_RETRY_WAIT = 120.0

# ✅ Clés OpenRouter (6 comptes)
_API_KEYS = [
    os.getenv("OPENROUTER_API_KEY_1", ""),
    os.getenv("OPENROUTER_API_KEY_2", ""),
    os.getenv("OPENROUTER_API_KEY_3", ""),
    os.getenv("OPENROUTER_API_KEY_4", ""),
    os.getenv("OPENROUTER_API_KEY_5", ""),
    os.getenv("OPENROUTER_API_KEY_6", ""),
]

# Filtrer les clés vides
_API_KEYS = [k for k in _API_KEYS if k and len(k) > 10]

if not _API_KEYS:
    _API_KEYS = [settings.OPENROUTER_API_KEY_1 or ""]
    _API_KEYS = [k for k in _API_KEYS if k]

logger.info(f"[LLM KEY] Loaded {len(_API_KEYS)} OpenRouter API key(s): {[k[:20]+'...' for k in _API_KEYS]}")

_current_key_index = 0


def _get_next_api_key() -> str:
    """Rotation circulaire des clés API OpenRouter."""
    global _current_key_index
    if not _API_KEYS:
        return settings.OPENROUTER_API_KEY_1 or ""
    key = _API_KEYS[_current_key_index]
    _current_key_index = (_current_key_index + 1) % len(_API_KEYS)
    return key


class ControlledChatOpenRouter(ChatOpenAI):
    """
    ChatOpenAI modifié pour OpenRouter avec :
    - Rotation de clés API
    - Pacing entre les appels
    - Retry automatique sur rate limit
    - Base URL OpenRouter
    """

    async def _agenerate(self, *args, **kwargs) -> Any:
        global _last_call_time

        async with llm_semaphore:
            # Pacing
            elapsed = time.monotonic() - _last_call_time
            if elapsed < _MIN_CALL_INTERVAL:
                await asyncio.sleep(_MIN_CALL_INTERVAL - elapsed)

            for attempt in range(len(_RETRY_DELAYS) + 1):
                try:
                    # Rotation de clé
                    self.openai_api_key = _get_next_api_key()
                    key_preview = self.openai_api_key[:20] + "..." if self.openai_api_key else "NO_KEY"
                    logger.info(f"[LLM KEY] 🚀 Calling OpenRouter with key: {key_preview} (attempt {attempt + 1})")

                    _last_call_time = time.monotonic()
                    result = await super()._agenerate(*args, **kwargs)
                    logger.info(f"[LLM KEY] ✅ Success with key: {key_preview}")
                    return result

                except RateLimitError as exc:
                    key_preview = self.openai_api_key[:20] + "..." if self.openai_api_key else "NO_KEY"
                    
                    if len(_API_KEYS) > 1:
                        logger.warning(f"[LLM KEY] ⚠️ Rate limited on key: {key_preview} — switching to next key...")
                        await asyncio.sleep(3)
                        continue
                    
                    if attempt == len(_RETRY_DELAYS):
                        logger.error(f"[LLM KEY] ❌ Rate limit exhausted after {len(_RETRY_DELAYS)} retries")
                        raise
                    
                    wait = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                    logger.warning(f"[LLM KEY] ⏳ Rate limited — retrying in {wait}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait)

                except Exception as exc:
                    key_preview = self.openai_api_key[:20] + "..." if self.openai_api_key else "NO_KEY"
                    logger.error(f"[LLM ERROR] OpenRouter call failed with key {key_preview}: {exc}")
                    raise


def create_llm(temperature: float, model: str, max_tokens: int) -> ControlledChatOpenRouter:
    """
    Crée un LLM connecté à OpenRouter.
    Modèles recommandés :
    - 'meta-llama/llama-3.3-70b-instruct' (gratuit)
    - 'google/gemma-2-9b-it' (gratuit)
    - 'mistralai/mistral-7b-instruct' (gratuit)
    """
    return ControlledChatOpenRouter(
        openai_api_key=_API_KEYS[0] if _API_KEYS else (settings.OPENROUTER_API_KEY_1 or ""),
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url="https://openrouter.ai/api/v1",  # ✅ URL OpenRouter
        default_headers={
            "HTTP-Referer": "http://localhost:4200",
            "X-Title": "TestForge AI",
        },
    )