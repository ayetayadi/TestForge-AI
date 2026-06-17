import asyncio
import logging
import os
import time
from contextvars import ContextVar
from typing import Any

import groq as _groq_lib
import openai as _openai_lib
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
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

_MIN_CALL_INTERVAL = 4.0
_last_call_times: dict[str, float] = {}

_RETRY_DELAYS = [15, 30, 60]
_MAX_RETRY_WAIT = 120.0

# ──────────────────────────────────────────────────────────────
# EXHAUSTION REGISTRY
# Maps raw API key → unix timestamp after which it is usable again.
# Set once on rate-limit, checked in O(1) before every call.
# Never cleared manually — the deadline IS the TTL.
# ──────────────────────────────────────────────────────────────

_exhausted_until: dict[str, float] = {}

def _mark_exhausted(key: str, retry_after: float) -> None:
    deadline = time.time() + retry_after
    _exhausted_until[key] = deadline
    label = _key_label(key)
    hours = retry_after / 3600
    logger.warning(
        f"[LLM KEY] 🚫 {label} exhausted for {retry_after:.0f}s "
        f"({hours:.1f}h) — will resume at {time.strftime('%H:%M:%S', time.localtime(deadline))}"
    )

def _is_available(key: str) -> bool:
    deadline = _exhausted_until.get(key, 0.0)
    if deadline == 0.0:
        return True
    if time.time() >= deadline:
        # Reset once the deadline passes
        del _exhausted_until[key]
        logger.info(f"[LLM KEY] ✅ {_key_label(key)} cooldown expired — back in pool")
        return True
    return False

def _available_groq_keys(exclude: str | None = None) -> list[str]:
    return [k for k in _GROQ_KEYS if k != exclude and _is_available(k)]

def _available_openrouter_keys() -> list[str]:
    return [k for k in _OPENROUTER_KEYS if _is_available(k)]

# ──────────────────────────────────────────────────────────────
# KEY POOLS
# ──────────────────────────────────────────────────────────────

_ALL_KEY_ENV_NAMES = (
    [f"GROQ_API_KEY_{i}" for i in range(1, 9)] +
    ["OPENROUTER_API_KEY"] +
    [f"OPENROUTER_API_KEY_{i}" for i in range(1, 7)] +
    ["AZURE_OPENAI_KEY_JUDGE"]
)

_KEY_NAME_MAP: dict[str, str] = {}
for _env_name in _ALL_KEY_ENV_NAMES:
    _val = os.getenv(_env_name, "")
    if _val and len(_val) > 10:
        _KEY_NAME_MAP[_val] = _env_name

_GROQ_KEYS: list[str] = [
    k for k in (os.getenv(f"GROQ_API_KEY_{i}", "") for i in range(1, 9))
    if k and len(k) > 10
]
if not _GROQ_KEYS:
    _fb = getattr(settings, "GROQ_API_KEY_1", "") or ""
    if _fb:
        _GROQ_KEYS = [_fb]

_OPENROUTER_KEYS: list[str] = [
    k for k in (
        os.getenv("OPENROUTER_API_KEY", ""),
        *[os.getenv(f"OPENROUTER_API_KEY_{i}", "") for i in range(1, 7)],
    )
    if k and len(k) > 10
]

# ── Azure OpenAI (final fallback — gpt-4.1) ──────────────────────
_AZURE_KEY: str = os.getenv("AZURE_OPENAI_KEY_JUDGE", "")
_AZURE_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT_JUDGE", "")
_AZURE_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT_JUDGE", "gpt-4.1")
_AZURE_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION_JUDGE", "2025-01-01-preview")
_AZURE_ENABLED: bool = bool(_AZURE_KEY and _AZURE_ENDPOINT and len(_AZURE_KEY) > 10)
if _AZURE_ENABLED:
    _KEY_NAME_MAP[_AZURE_KEY] = "AZURE_OPENAI_KEY_JUDGE"

logger.info(
    f"[LLM KEY] Groq pool: {[_KEY_NAME_MAP.get(k, k[:12]+'...') for k in _GROQ_KEYS]} | "
    f"OpenRouter pool: {[_KEY_NAME_MAP.get(k, k[:12]+'...') for k in _OPENROUTER_KEYS]} | "
    f"Azure fallback: {'gpt-4.1 (' + _AZURE_DEPLOYMENT + ')' if _AZURE_ENABLED else 'OFF'}"
)

# ──────────────────────────────────────────────────────────────
# MODEL NAME MAPPING  (Groq name → OpenRouter name)
# ──────────────────────────────────────────────────────────────

_GROQ_TO_OPENROUTER: dict[str, str] = {
    "openai/gpt-oss-120b":   "meta-llama/llama-3.3-70b-instruct",
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
    """Round-robin over available (non-exhausted) Groq keys."""
    global _current_key_index
    available = _available_groq_keys()
    if not available:
        # All exhausted — return the one whose cooldown expires soonest
        if _GROQ_KEYS:
            soonest = min(_GROQ_KEYS, key=lambda k: _exhausted_until.get(k, 0.0))
            logger.warning(f"[LLM KEY] All Groq keys exhausted — picking soonest: {_key_label(soonest)}")
            return soonest
        return getattr(settings, "GROQ_API_KEY_1", "") or ""
    # Rotate within the available subset
    _current_key_index = _current_key_index % len(available)
    key = available[_current_key_index]
    _current_key_index = (_current_key_index + 1) % len(available)
    return key


def set_worker_api_key(key: str) -> None:
    _worker_api_key.set(key)
    logger.info(f"[LLM KEY] ✅ Worker key set: {_key_label(key)}")


def get_worker_api_key() -> str | None:
    return _worker_api_key.get()


# ──────────────────────────────────────────────────────────────
# DIRECT CALL HELPERS
# ──────────────────────────────────────────────────────────────

def _messages_to_dicts(messages: list) -> list[dict]:
    role_map = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}
    result = []
    for m in messages:
        role = role_map.get(getattr(m, "type", "human"), "user")
        result.append({"role": role, "content": getattr(m, "content", str(m))})
    return result


def _tool_calls_to_additional_kwargs(tool_calls) -> dict:
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
    client = _groq_lib.AsyncGroq(api_key=key, max_retries=0)
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


async def _direct_azure_call(
    model: str, temperature: float, max_tokens: int, messages: list,
    tools: list | None = None, tool_choice=None,
) -> ChatResult:
    """Call Azure OpenAI (gpt-4.1) directly. `model` arg is ignored — Azure
    routes by deployment name, not model name."""
    client = _openai_lib.AsyncAzureOpenAI(
        api_key=_AZURE_KEY,
        azure_endpoint=_AZURE_ENDPOINT,
        api_version=_AZURE_API_VERSION,
    )
    params: dict = dict(
        model=_AZURE_DEPLOYMENT,
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
                retry_after = _read_retry_after(headers) or 3600.0
                return False, retry_after
            retry_after = _read_retry_after(headers)
            if retry_after is not None:
                if retry_after > _MAX_RETRY_WAIT:
                    return False, retry_after
                return True, retry_after
    except Exception:
        pass
    return True, _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]


def _read_retry_after(headers) -> float | None:
    for header in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        val = headers.get(header)
        if val:
            try:
                return float(val)
            except ValueError:
                pass
    return None


def _read_openrouter_retry_after(exc: _openai_lib.RateLimitError) -> float:
    try:
        response = getattr(exc, "response", None)
        if response is not None:
            val = response.headers.get("retry-after")
            if val:
                return float(val)
    except Exception:
        pass
    return 3600.0


# ──────────────────────────────────────────────────────────────
# CONTROLLED CHAT GROQ
# ──────────────────────────────────────────────────────────────

class ControlledChatGroq(ChatGroq):
    """
    ChatGroq with per-key semaphore, pacing, and 3-tier key fallback.

    Keys are marked exhausted (with exact retry-after deadline) on first
    rate-limit hit. All subsequent calls skip exhausted keys instantly via
    _is_available() — zero wasted API calls during the cooldown window.

      Tier 1 — Primary Groq key:  retry up to len(_RETRY_DELAYS) times
      Tier 2 — Other available Groq keys: try each once (skip exhausted)
      Tier 3 — Available OpenRouter keys: try each once (skip exhausted)
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
        tools = kwargs.get("tools")
        tool_choice = kwargs.get("tool_choice")
        last_exc: Exception | None = None
        retry_wait = 0.0

        # ── Tier 1: primary Groq key ──────────────────────────────────────
        if not _is_available(key_id):
            deadline = _exhausted_until.get(key_id, 0)
            remaining = max(0, deadline - time.time())
            logger.warning(
                f"[LLM KEY] ⏭ Skipping exhausted primary key {key_preview} "
                f"({remaining:.0f}s remaining) — going straight to fallbacks"
            )
        else:
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
                        # IMMEDIATE ROTATION (Groq only): if another Groq key is
                        # free, don't burn `wait` seconds sleeping on this one —
                        # mark it exhausted for its cooldown and break straight to
                        # Tier 2 so a fresh key handles this turn now. We only ever
                        # sleep-and-retry the same key when it's the ONLY one left.
                        if _available_groq_keys(exclude=key_id):
                            _mark_exhausted(key_id, wait)
                            logger.info(
                                f"[LLM KEY] ↪ {key_preview} rate-limited — rotating "
                                f"immediately to a free Groq key (skipping {wait:.0f}s wait)"
                            )
                            break
                        if not should_retry or attempt == len(_RETRY_DELAYS):
                            _mark_exhausted(key_id, wait)
                            break
                        retry_wait = wait

                    except Exception as exc:
                        logger.error(f"[LLM ERROR] {key_preview}: {exc}")
                        raise

        # ── Tier 2: other available Groq keys ────────────────────────────
        for fb_key in _available_groq_keys(exclude=key_id):
            fb_label = _key_label(fb_key)
            fb_sem = _get_key_semaphore(fb_key)

            last_call = _last_call_times.get(fb_key, 0.0)
            gap = _MIN_CALL_INTERVAL - (time.monotonic() - last_call)
            if gap > 0:
                await asyncio.sleep(gap)

            async with fb_sem:
                try:
                    logger.info(f"[LLM KEY] 🔄 Groq fallback → {fb_label}")
                    _last_call_times[fb_key] = time.monotonic()
                    result = await _direct_groq_call(
                        fb_key, self.model_name, self.temperature, self.max_tokens, messages,
                        tools=tools, tool_choice=tool_choice,
                    )
                    logger.info(f"[LLM KEY] ✅ Groq fallback success — key: {fb_label}")
                    return result

                except GroqRateLimitError as exc:
                    last_exc = exc
                    _, wait = _parse_rate_limit(exc, 0)
                    _mark_exhausted(fb_key, wait)
                    continue

                except Exception as exc:
                    logger.error(f"[LLM ERROR] Groq fallback {fb_label}: {exc}")
                    raise

        # ── Tier 3: Azure OpenAI (gpt-4.1) — preferred fallback ──────────
        if _AZURE_ENABLED and _is_available(_AZURE_KEY):
            last_call = _last_call_times.get(_AZURE_KEY, 0.0)
            gap = _MIN_CALL_INTERVAL - (time.monotonic() - last_call)
            if gap > 0:
                await asyncio.sleep(gap)
            try:
                logger.warning(
                    f"[LLM AZURE] All Groq keys exhausted — falling back to "
                    f"Azure OpenAI ({_AZURE_DEPLOYMENT})"
                )
                _last_call_times[_AZURE_KEY] = time.monotonic()
                result = await _direct_azure_call(
                    self.model_name, self.temperature, self.max_tokens, messages,
                    tools=tools, tool_choice=tool_choice,
                )
                logger.info(f"[LLM AZURE] ✅ Azure fallback success — {_AZURE_DEPLOYMENT}")
                return result
            except _openai_lib.RateLimitError as exc:
                last_exc = exc
                wait = _read_openrouter_retry_after(exc)
                _mark_exhausted(_AZURE_KEY, wait)
            except Exception as exc:
                logger.error(f"[LLM AZURE] Azure fallback failed: {exc}")
                last_exc = exc

        # ── Tier 4: available OpenRouter keys — last resort ──────────────
        available_or = _available_openrouter_keys()
        if available_or:
            logger.warning(
                f"[LLM KEY] Groq + Azure exhausted — switching to OpenRouter "
                f"({len(available_or)}/{len(_OPENROUTER_KEYS)} keys available)"
            )

            for or_key in available_or:
                or_label = _key_label(or_key)
                or_sem = _get_key_semaphore(or_key)

                last_call = _last_call_times.get(or_key, 0.0)
                gap = _MIN_CALL_INTERVAL - (time.monotonic() - last_call)
                if gap > 0:
                    await asyncio.sleep(gap)

                async with or_sem:
                    try:
                        logger.info(f"[LLM OR] 🔄 Trying OpenRouter key: {or_label}")
                        _last_call_times[or_key] = time.monotonic()
                        result = await _direct_openrouter_call(
                            or_key, self.model_name, self.temperature, self.max_tokens, messages,
                            tools=tools, tool_choice=tool_choice,
                        )
                        logger.info(f"[LLM OR] ✅ OpenRouter success — key: {or_label}")
                        return result

                    except _openai_lib.RateLimitError as exc:
                        last_exc = exc
                        wait = _read_openrouter_retry_after(exc)
                        _mark_exhausted(or_key, wait)
                        continue

                    except _openai_lib.APIStatusError as exc:
                        # 402 insufficient credits — mark exhausted, try next key
                        if getattr(exc, "status_code", None) == 402:
                            last_exc = exc
                            logger.warning(
                                f"[LLM OR] {or_label}: 402 insufficient credits — "
                                "marking exhausted 24h, moving on"
                            )
                            _mark_exhausted(or_key, 86400.0)
                            continue
                        logger.error(f"[LLM OR] OpenRouter call failed — key {or_label}: {exc}")
                        last_exc = exc
                        break

                    except Exception as exc:
                        logger.error(f"[LLM OR] OpenRouter call failed — key {or_label}: {exc}")
                        last_exc = exc
                        break

        logger.error("[LLM KEY] All Groq + Azure + OpenRouter keys exhausted")
        raise last_exc or RuntimeError("All Groq, Azure and OpenRouter API keys exhausted")


# ──────────────────────────────────────────────────────────────
# PUBLIC FACTORY
# ──────────────────────────────────────────────────────────────

def create_llm(temperature: float, model: str, max_tokens: int) -> ControlledChatGroq:
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
        max_retries=0,
    )


# ──────────────────────────────────────────────────────────────
# AVAILABLE MODELS CATALOG
# ──────────────────────────────────────────────────────────────

AVAILABLE_MODELS = [
    {
        "id": "llama-3.3-70b-versatile",
        "label": "LLaMA 3.3 70B (Groq)",
        "provider": "groq",
        "description": "Fast structured output, best for locator resolution. Default.",
        "is_default": True,
    },
    {
        "id": "google/gemini-2.5-flash",
        "label": "Gemini 2.5 Flash",
        "provider": "openrouter",
        "description": "1M context window, excellent code quality. Best for complex projects.",
        "is_default": False,
    },
    {
        "id": "meta-llama/llama-3.3-70b-instruct",
        "label": "LLaMA 3.3 70B (OpenRouter)",
        "provider": "openrouter",
        "description": "Same LLaMA model via OpenRouter as Groq fallback.",
        "is_default": False,
    },
]


def get_available_models() -> list:
    return AVAILABLE_MODELS


# ──────────────────────────────────────────────────────────────
# OPENROUTER-DIRECT LLM  (for models not on Groq: Gemini, Claude, etc.)
# ──────────────────────────────────────────────────────────────

class ControlledOpenRouterLLM(ChatOpenAI):
    """
    ChatOpenAI targeting OpenRouter with key rotation + rate-limit handling.
    Used for models that are only available on OpenRouter (Gemini, Claude, etc.)
    and do NOT go through the Groq pool at all.
    """

    def _get_key_id(self) -> str:
        k = self.openai_api_key
        return k.get_secret_value() if hasattr(k, "get_secret_value") else str(k)

    @staticmethod
    def _is_payment_error(exc: Exception) -> bool:
        """Return True for HTTP 402 — insufficient credits on this OpenRouter account."""
        return (
            isinstance(exc, _openai_lib.APIStatusError)
            and getattr(exc, "status_code", None) == 402
        )

    async def _agenerate(self, *args, **kwargs) -> Any:
        messages = args[0] if args else kwargs.get("messages", [])
        tools = kwargs.get("tools")
        tool_choice = kwargs.get("tool_choice")
        key_id = self._get_key_id()
        key_label = _key_label(key_id)
        last_exc: Exception | None = None

        # Try primary key first (the one baked into the instance)
        if _is_available(key_id):
            try:
                logger.info(f"[LLM OR] 🚀 OpenRouter call — model: {self.model_name}, key: {key_label}")
                result = await super()._agenerate(*args, **kwargs)
                logger.info(f"[LLM OR] ✅ Success — key: {key_label}")
                return result
            except _openai_lib.RateLimitError as exc:
                last_exc = exc
                wait = _read_openrouter_retry_after(exc)
                _mark_exhausted(key_id, wait)
            except _openai_lib.APIStatusError as exc:
                if self._is_payment_error(exc):
                    last_exc = exc
                    logger.warning(
                        f"[LLM OR] {key_label}: 402 insufficient credits — "
                        "marking exhausted for 24h, rotating key"
                    )
                    _mark_exhausted(key_id, 86400.0)
                else:
                    logger.error(f"[LLM OR] {key_label}: {exc}")
                    raise
            except Exception as exc:
                logger.error(f"[LLM OR] {key_label}: {exc}")
                raise

        # Rotate through other available OpenRouter keys
        for or_key in _available_openrouter_keys():
            if or_key == key_id:
                continue
            or_label = _key_label(or_key)
            try:
                logger.info(f"[LLM OR] 🔄 Fallback OpenRouter key: {or_label}")
                result = await _direct_openrouter_call(
                    or_key, self.model_name, self.temperature, self.max_tokens,
                    messages, tools=tools, tool_choice=tool_choice,
                )
                logger.info(f"[LLM OR] ✅ Fallback success — key: {or_label}")
                return result
            except _openai_lib.RateLimitError as exc:
                last_exc = exc
                wait = _read_openrouter_retry_after(exc)
                _mark_exhausted(or_key, wait)
            except _openai_lib.APIStatusError as exc:
                if self._is_payment_error(exc):
                    last_exc = exc
                    logger.warning(
                        f"[LLM OR] {or_label}: 402 insufficient credits — skipping key"
                    )
                    _mark_exhausted(or_key, 86400.0)
                else:
                    logger.error(f"[LLM OR] {or_label}: {exc}")
                    raise
            except Exception as exc:
                logger.error(f"[LLM OR] {or_label}: {exc}")
                raise

        # All OpenRouter keys exhausted (rate-limited or out of credits)
        # → fall back to Groq LLaMA 3.3 70B so the request still succeeds
        logger.warning(
            f"[LLM OR] All OpenRouter keys exhausted for model={self.model_name}. "
            "Falling back to Groq openai/gpt-oss-120b."
        )
        try:
            groq_llm = create_llm(
                self.temperature,
                "openai/gpt-oss-120b",
                self.max_tokens,
            )
            result = await groq_llm._agenerate(*args, **kwargs)
            logger.info("[LLM OR] ✅ Groq fallback succeeded")
            return result
        except Exception as fb_exc:
            logger.error(f"[LLM OR] Groq fallback also failed: {fb_exc}")
            raise last_exc or fb_exc


def create_openrouter_llm(model_id: str, temperature: float, max_tokens: int) -> ControlledOpenRouterLLM:
    """Create an LLM that calls OpenRouter directly (for Gemini, Claude, etc.)."""
    keys = _available_openrouter_keys()
    if not keys:
        keys = _OPENROUTER_KEYS  # use anyway, rate-limit handler will rotate
    if not keys:
        raise RuntimeError("No OpenRouter API keys configured")
    key = keys[0]
    logger.info(f"[LLM OR] create_openrouter_llm → model={model_id}, key={_key_label(key)}")
    return ControlledOpenRouterLLM(
        api_key=key,
        base_url="https://openrouter.ai/api/v1",
        model=model_id,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def create_llm_for_model(model_id: str, temperature: float, max_tokens: int):
    """
    Route to the correct LLM backend based on model_id.
    - model_id contains '/' → OpenRouter model (Gemini, Claude, OpenRouter-hosted LLaMA)
    - otherwise → Groq model with Groq→OpenRouter fallback chain
    """
    if "/" in model_id:
        return create_openrouter_llm(model_id, temperature, max_tokens)
    return create_llm(temperature, model_id, max_tokens)
