import asyncio
import logging
import time
from typing import Any
from langchain_groq import ChatGroq
from groq import RateLimitError
from app.core.config import settings

logger = logging.getLogger(__name__)

# Serialize all outgoing LLM calls — one at a time to avoid bursts
llm_semaphore = asyncio.Semaphore(1)

# Minimum gap between consecutive API calls: 24 req/min, well under Groq's 30 RPM limit
_MIN_CALL_INTERVAL = 2.5  # seconds
_last_call_time: float = 0.0

# Retry delays (seconds) when Groq returns 429 — overridden by retry-after header if present
_RETRY_DELAYS = [10, 30, 60]

# If Groq says retry-after > this threshold, fail immediately instead of blocking the worker.
# This handles daily quota exhaustion (retry-after can be 500+ seconds).
_MAX_RETRY_WAIT = 30.0


class ControlledChatGroq(ChatGroq):
    """ChatGroq with global serialization, inter-call pacing, and rate-limit retry."""

    async def _agenerate(self, *args, **kwargs) -> Any:
        global _last_call_time

        async with llm_semaphore:
            # Pace: enforce a minimum gap since the last API call
            elapsed = time.monotonic() - _last_call_time
            if elapsed < _MIN_CALL_INTERVAL:
                await asyncio.sleep(_MIN_CALL_INTERVAL - elapsed)

            for attempt in range(len(_RETRY_DELAYS) + 1):
                try:
                    _last_call_time = time.monotonic()
                    result = await super()._agenerate(*args, **kwargs)
                    logger.debug("[LLM] Response received from Groq")
                    return result

                except RateLimitError as exc:
                    should_retry, wait = _parse_rate_limit(exc, attempt)
                    if not should_retry:
                        logger.error(
                            f"[LLM] Rate limit — Groq said do not retry "
                            f"(retry-after={wait}s). Failing job immediately."
                        )
                        raise
                    if attempt == len(_RETRY_DELAYS):
                        logger.error("[LLM] Rate limit exceeded after all retries")
                        raise
                    logger.warning(
                        f"[LLM] Rate limited — retrying in {wait}s "
                        f"(attempt {attempt + 1}/{len(_RETRY_DELAYS)})"
                    )
                    await asyncio.sleep(wait)

                except Exception as exc:
                    logger.error(f"[LLM ERROR] Groq call failed: {exc}")
                    raise


def _parse_rate_limit(exc: RateLimitError, attempt: int) -> tuple[bool, float]:
    """
    Returns (should_retry, wait_seconds).

    Fails immediately (should_retry=False) when:
    - Groq sets x-should-retry: false, OR
    - retry-after exceeds _MAX_RETRY_WAIT (daily quota exhausted)
    """
    try:
        response = getattr(exc, "response", None)
        if response is not None:
            headers = response.headers

            # Groq explicitly says don't retry
            if headers.get("x-should-retry", "").lower() == "false":
                retry_after = _read_retry_after(headers)
                return False, retry_after or 0.0

            retry_after = _read_retry_after(headers)
            if retry_after is not None:
                # Long wait = daily/hourly quota hit → fail fast
                if retry_after > _MAX_RETRY_WAIT:
                    logger.warning(
                        f"[LLM] retry-after={retry_after}s > {_MAX_RETRY_WAIT}s threshold "
                        f"— daily quota likely exhausted, failing job."
                    )
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
    return ControlledChatGroq(
        groq_api_key=settings.GROQ_API_KEY,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
