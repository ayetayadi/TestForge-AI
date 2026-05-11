import asyncio
import logging
import os
import time
from contextvars import ContextVar
from typing import Any

import groq as _groq_lib
import openai as _openai_lib
from langchain_groq import ChatGroq
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.messages import AIMessage
from groq import RateLimitError as GroqRateLimitError
from app.core.config import settings
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# SEMAPHORES & PACING
# ──────────────────────────────────────────────────────────────

_key_semaphores: dict[str, asyncio.Semaphore] = {}

def _get_key_semaphore(key_id: str) -> asyncio.Semaphore:
    if key_id not in _key_semaphores:
        _key_semaphores[key_id] = asyncio.Semaphore(1)
    return _key_semaphores[key_id]

_MIN_CALL_INTERVAL = 10.0
_last_call_times: dict[str, float] = {}

_RETRY_DELAYS = [15, 30, 60]
_MAX_RETRY_WAIT = 120.0

# ──────────────────────────────────────────────────────────────
# KEY POOLS
# ──────────────────────────────────────────────────────────────

_ALL_KEY_ENV_NAMES = (
    [f"GROQ_API_KEY_{i}" for i in range(1, 6)] +
    ["OPENROUTER_API_KEY"] +
    [f"OPENROUTER_API_KEY_{i}" for i in range(1, 7)]
)

# Reverse map: raw_key → env var name  (e.g. "gsk_abc..." → "GROQ_API_KEY_2")
_KEY_NAME_MAP: dict[str, str] = {}
for _env_name in _ALL_KEY_ENV_NAMES:
    _val = os.getenv(_env_name, "")
    if _val and len(_val) > 10:
        _KEY_NAME_MAP[_val] = _env_name

# Groq pool
_GROQ_KEYS: list[str] = [
    k for k in (os.getenv(f"GROQ_API_KEY_{i}", "") for i in range(1, 6))
    if k and len(k) > 10
]
if not _GROQ_KEYS:
    _fb = getattr(settings, "GROQ_API_KEY_1", "") or ""
    if _fb:
        _GROQ_KEYS = [_fb]

# OpenRouter pool
_OPENROUTER_KEYS: list[str] = [
    k for k in (
        os.getenv("OPENROUTER_API_KEY", ""),
        *[os.getenv(f"OPENROUTER_API_KEY_{i}", "") for i in range(1, 7)],
    )
    if k and len(k) > 10
]

logger.info(
    f"[LLM KEY] Groq pool: {[_KEY_NAME_MAP.get(k, k[:12]+'...') for k in _GROQ_KEYS]} | "
    f"OpenRouter pool: {[_KEY_NAME_MAP.get(k, k[:12]+'...') for k in _OPENROUTER_KEYS]}"
)

# ──────────────────────────────────────────────────────────────
# MODEL NAME MAPPING  (Groq name → OpenRouter name)
# ──────────────────────────────────────────────────────────────

_GROQ_TO_OPENROUTER: dict[str, str] = {
    "llama-3.3-70b-versatile":   "meta-llama/llama-3.3-70b-instruct",
    "llama-3.1-70b-versatile":   "meta-llama/llama-3.1-70b-instruct",
    "llama-3.1-8b-instant":      "meta-llama/llama-3.1-8b-instruct",
    "llama3-70b-8192":           "meta-llama/llama-3-70b-instruct",
    "llama3-8b-8192":            "meta-llama/llama-3-8b-instruct",
    "mixtral-8x7b-32768":        "mistralai/mixtral-8x7b-instruct",
    "gemma2-9b-it":              "google/gemma-2-9b-it",
    "gemma-7b-it":               "google/gemma-7b-it",
}

# ──────────────────────────────────────────────────────────────
# WORKER KEY  (ContextVar — one key per asyncio task)
# ──────────────────────────────────────────────────────────────

_worker_api_key: ContextVar[str | None] = ContextVar("worker_api_key", default=None)
_current_key_index = 0


def _key_label(key: str) -> str:
    return _KEY_NAME_MAP.get(key, key[:12] + "...")


def _get_next_groq_key() -> str:
    global _current_key_index
    if not _GROQ_KEYS:
        return getattr(settings, "GROQ_API_KEY_1", "") or ""
    key = _GROQ_KEYS[_current_key_index]
    _current_key_index = (_current_key_index + 1) % len(_GROQ_KEYS)
    logger.info(f"[LLM KEY] 🔄 Fallback rotation → {_key_label(key)}")
    return key


def set_worker_api_key(key: str) -> None:
    _worker_api_key.set(key)
    logger.info(f"[LLM KEY] ✅ Worker key set: {_key_label(key)}")


def get_worker_api_key() -> str | None:
    return _worker_api_key.get()


# ──────────────────────────────────────────────────────────────
# DIRECT CALL HELPERS
# These bypass LangChain so we can swap keys without mutating
# a shared ChatGroq instance.
# ──────────────────────────────────────────────────────────────

def _messages_to_dicts(messages: list) -> list[dict]:
    role_map = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}
    result = []
    for m in messages:
        role = role_map.get(getattr(m, "type", "human"), "user")
        result.append({"role": role, "content": getattr(m, "content", str(m))})
    return result


def _tool_calls_to_additional_kwargs(tool_calls) -> dict:
    """Convert raw API tool_calls list to LangChain additional_kwargs format."""
    if not tool_calls:
        return {}
    return {
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in tool_calls
        ]
    }


async def _direct_groq_call(
    key: str, model: str, temperature: float, max_tokens: int, messages: list,
    tools: list | None = None, tool_choice=None,
) -> ChatResult:
    """Call Groq directly with an arbitrary key (used for key-rotation fallbacks)."""
    client = _groq_lib.AsyncGroq(api_key=key)
    params: dict = dict(
        model=model,
        messages=_messages_to_dicts(messages),
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if tools:
        params["tools"] = tools
    if tool_choice is not None:
        params["tool_choice"] = tool_choice
    response = await client.chat.completions.create(**params)
    msg = response.choices[0].message
    content = msg.content or ""
    additional_kwargs = _tool_calls_to_additional_kwargs(msg.tool_calls)
    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content, additional_kwargs=additional_kwargs))])


async def _direct_openrouter_call(
    key: str, model: str, temperature: float, max_tokens: int, messages: list,
    tools: list | None = None, tool_choice=None,
) -> ChatResult:
    """
    Call OpenRouter using the openai-compatible client.
    Model name is translated from Groq format to OpenRouter format automatically.
    Used as last-resort fallback when all Groq keys are rate-limited.
    """
    or_model = _GROQ_TO_OPENROUTER.get(model, model)
    logger.info(f"[LLM OR] Using OpenRouter model: {or_model} (mapped from '{model}')")

    client = _openai_lib.AsyncOpenAI(
        api_key=key,
        base_url="https://openrouter.ai/api/v1",
    )
    params: dict = dict(
        model=or_model,
        messages=_messages_to_dicts(messages),
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if tools:
        params["tools"] = tools
    if tool_choice is not None:
        params["tool_choice"] = tool_choice
    response = await client.chat.completions.create(**params)
    msg = response.choices[0].message
    content = msg.content or ""
    additional_kwargs = _tool_calls_to_additional_kwargs(msg.tool_calls)
    return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content, additional_kwargs=additional_kwargs))])


# ──────────────────────────────────────────────────────────────
# RATE LIMIT HELPERS
# ──────────────────────────────────────────────────────────────

def _parse_rate_limit(exc: GroqRateLimitError, attempt: int) -> tuple[bool, float]:
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
                    logger.warning(f"[LLM KEY] retry-after={retry_after}s > {_MAX_RETRY_WAIT}s — skipping key")
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


# ──────────────────────────────────────────────────────────────
# CONTROLLED CHAT GROQ
# ──────────────────────────────────────────────────────────────

class ControlledChatGroq(ChatGroq):
    """
    ChatGroq with per-key semaphore, pacing, and 3-tier key fallback:

      Tier 1 — Primary Groq key:  retry up to len(_RETRY_DELAYS) times
      Tier 2 — Other Groq keys:   try each key in _GROQ_KEYS once
      Tier 3 — OpenRouter keys:   try each OR key once, translated model name
    """

    def _get_key_id(self) -> str:
        k = self.groq_api_key
        if k is None:
            return "NO_KEY"
        return k.get_secret_value() if hasattr(k, "get_secret_value") else str(k)

    async def _agenerate(self, *args, **kwargs) -> Any:
        key_id = self._get_key_id()
        key_preview = _key_label(key_id)
        sem = _get_key_semaphore(key_id)
        messages = args[0] if args else kwargs.get("messages", [])
        # Preserve tool-calling params so fallback calls also use structured output
        tools = kwargs.get("tools")
        tool_choice = kwargs.get("tool_choice")
        last_exc: Exception | None = None
        retry_wait = 0.0

        # ── Tier 1: primary Groq key with retries ─────────────────────────
        for attempt in range(len(_RETRY_DELAYS) + 1):
            if retry_wait > 0:
                logger.warning(
                    f"[LLM KEY] ⏳ Waiting {retry_wait:.0f}s before retry "
                    f"{attempt}/{len(_RETRY_DELAYS)} (key {key_preview})"
                )
                await asyncio.sleep(retry_wait)
                retry_wait = 0.0

            last_call = _last_call_times.get(key_id, 0.0)
            elapsed = time.monotonic() - last_call
            if elapsed < _MIN_CALL_INTERVAL:
                await asyncio.sleep(_MIN_CALL_INTERVAL - elapsed)

            async with sem:
                try:
                    logger.info(f"[LLM KEY] 🚀 Groq call — key: {key_preview} (attempt {attempt + 1})")
                    _last_call_times[key_id] = time.monotonic()
                    result = await super()._agenerate(*args, **kwargs)
                    logger.info(f"[LLM KEY] ✅ Success — key: {key_preview}")
                    return result

                except GroqRateLimitError as exc:
                    last_exc = exc
                    should_retry, wait = _parse_rate_limit(exc, attempt)
                    if not should_retry or attempt == len(_RETRY_DELAYS):
                        logger.error(
                            f"[LLM KEY] ❌ {key_preview} exhausted — "
                            f"falling back to {len([k for k in _GROQ_KEYS if k != key_id])} "
                            f"Groq key(s) + {len(_OPENROUTER_KEYS)} OpenRouter key(s)"
                        )
                        break
                    retry_wait = wait

                except Exception as exc:
                    logger.error(f"[LLM ERROR] {key_preview}: {exc}")
                    raise

        # ── Tier 2: other Groq keys ────────────────────────────────────────
        for fb_key in [k for k in _GROQ_KEYS if k != key_id]:
            fb_label = _key_label(fb_key)
            fb_sem = _get_key_semaphore(fb_key)

            last_call = _last_call_times.get(fb_key, 0.0)
            if time.monotonic() - last_call < _MIN_CALL_INTERVAL:
                await asyncio.sleep(_MIN_CALL_INTERVAL - (time.monotonic() - last_call))

            async with fb_sem:
                try:
                    logger.warning(f"[LLM KEY] 🔄 Groq rotation: {key_preview} → {fb_label}")
                    _last_call_times[fb_key] = time.monotonic()
                    result = await _direct_groq_call(
                        fb_key, self.model_name, self.temperature, self.max_tokens, messages,
                        tools=tools, tool_choice=tool_choice,
                    )
                    logger.info(f"[LLM KEY] ✅ Groq fallback success — key: {fb_label}")
                    return result

                except GroqRateLimitError as exc:
                    last_exc = exc
                    logger.warning(f"[LLM KEY] ❌ Groq fallback {fb_label} also rate-limited")
                    continue

                except Exception as exc:
                    logger.error(f"[LLM ERROR] Groq fallback {fb_label}: {exc}")
                    raise

        # ── Tier 3: OpenRouter keys ────────────────────────────────────────
        if not _OPENROUTER_KEYS:
            logger.error("[LLM KEY] All Groq keys exhausted and no OpenRouter keys configured")
            raise last_exc or RuntimeError("All Groq API keys exhausted")

        logger.warning(
            f"[LLM KEY] All {len(_GROQ_KEYS)} Groq key(s) exhausted — "
            f"switching to OpenRouter ({len(_OPENROUTER_KEYS)} key(s))"
        )

        for or_key in _OPENROUTER_KEYS:
            or_label = _key_label(or_key)
            or_sem = _get_key_semaphore(or_key)

            last_call = _last_call_times.get(or_key, 0.0)
            if time.monotonic() - last_call < _MIN_CALL_INTERVAL:
                await asyncio.sleep(_MIN_CALL_INTERVAL - (time.monotonic() - last_call))

            async with or_sem:
                try:
                    logger.warning(f"[LLM OR] 🔄 Trying OpenRouter key: {or_label}")
                    _last_call_times[or_key] = time.monotonic()
                    result = await _direct_openrouter_call(
                        or_key, self.model_name, self.temperature, self.max_tokens, messages,
                        tools=tools, tool_choice=tool_choice,
                    )
                    logger.info(f"[LLM OR] ✅ OpenRouter success — key: {or_label}")
                    return result

                except _openai_lib.RateLimitError as exc:
                    last_exc = exc
                    logger.warning(f"[LLM OR] ❌ OpenRouter key {or_label} also rate-limited")
                    continue

                except Exception as exc:
                    logger.error(f"[LLM OR] OpenRouter call failed — key {or_label}: {exc}")
                    raise

        logger.error("[LLM KEY] All Groq AND OpenRouter keys exhausted")
        raise last_exc or RuntimeError("All Groq and OpenRouter API keys exhausted")


# ──────────────────────────────────────────────────────────────
# PUBLIC FACTORY
# ──────────────────────────────────────────────────────────────

def create_llm(temperature: float, model: str, max_tokens: int) -> ControlledChatGroq:
    """
    Creates a ControlledChatGroq using the worker-assigned key (ContextVar).
    Falls back to round-robin rotation if no worker key is set.
    """
    key = _worker_api_key.get()
    if key:
        logger.info(f"[LLM KEY] create_llm → worker key: {_key_label(key)}")
    else:
        key = _get_next_groq_key()
        logger.info(f"[LLM KEY] create_llm → rotation key: {_key_label(key)}")

    return ControlledChatGroq(
        groq_api_key=key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
