import asyncio
import random
from typing import Dict, Any, Optional
from dataclasses import dataclass
from langsmith import get_current_run_tree, traceable

from app.llm.factory import get_llm
from app.llm.fallbacks import FALLBACKS
from app.llm.utils import parse_and_validate
from app.core.cache import LLMCache


# =========================
# CONFIG
# =========================
LLM_TEMPERATURES = {
    "analysis": 0.2,
    "evaluation": 0.2,
    "refinement": 0.6,
}

# limite globale des appels LLM
LLM_SEMAPHORE = asyncio.Semaphore(5)


# =========================
# RESPONSE MODEL
# =========================
@dataclass
class LLMResponse:
    success: bool
    content: Dict[str, Any]
    error: Optional[str] = None
    model: Optional[str] = None
    prompt_tokens: Optional[int] = 0
    completion_tokens: Optional[int] = 0
    duration: Optional[float] = 0.0


# =========================
# SERVICE
# =========================
class LLMService:

    @traceable(name="llm_call", metadata={"version": "1.0"})
    async def call(
        self,
        prompt: str,
        task: str,
        temperature: Optional[float] = None,
        max_retries: int = 2,
        use_cache: bool = True
    ) -> LLMResponse:
        
        print(f"[LLM CALL] task={task}, use_cache={use_cache}")

        run = get_current_run_tree()
        if run:
            run.metadata["task"] = task
            run.metadata["model"] = get_llm(task).model
            run.metadata["temperature"] = temperature or LLM_TEMPERATURES.get(task)
            
        if temperature is None:
            temperature = LLM_TEMPERATURES.get(task, 0.5)

        cache_key = LLMCache.make_key(task, prompt)

        # =========================
        # CACHE GET
        # =========================
        if use_cache:
            cached = await LLMCache.get(cache_key)
            if cached:
                print(f"[LLM CACHE HIT] {task}")
                return LLMResponse(
                    success=True,
                    content=cached,
                    model=get_llm(task).model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    duration=0.0,
                )
        else:
            print(f"[LLM CACHE SKIP] {task}")

        llm = get_llm(task)

        # =========================
        # RETRY LOOP
        # =========================
        for attempt in range(max_retries):
            try:
                # SEMAPHORE → protège contre rate limit
                async with LLM_SEMAPHORE:
                    await asyncio.sleep(0.2)
                    response = await llm.generate_async(prompt, temperature)

                if response.get("llm_failed"):
                    print(f"[LLM HARD FAIL] {task} attempt {attempt+1}")
                    continue

                parsed = parse_and_validate(task, response)

                # fallback détecté → retry
                if parsed == FALLBACKS.get(task):
                    print(f"[LLM FALLBACK DETECTED] {task} attempt {attempt+1}")
                    continue

                # =========================
                # CACHE SET
                # =========================
                if use_cache:
                    await LLMCache.set(cache_key, parsed)

                return LLMResponse(
                    success=True,
                    content=parsed,
                    model=llm.model,
                    prompt_tokens=response.get("prompt_tokens", 0),
                    completion_tokens=response.get("completion_tokens", 0),
                    duration=response.get("duration", 0.0),
                )

            except Exception as e:
                print(f"[LLM ERROR] attempt {attempt+1}: {e}")

                # backoff exponentiel + jitter
                base = 2 ** attempt
                jitter = random.uniform(0, base * 0.3)
                await asyncio.sleep(base + jitter)

        # =========================
        # FINAL FALLBACK
        # =========================
        print(f"[LLM FINAL FALLBACK] {task}")

        return LLMResponse(
            success=True,
            content=FALLBACKS.get(task),
            error="LLM failed, fallback used",
            model=llm.model,
            prompt_tokens=0,
            completion_tokens=0,
            duration=0.0,
        )


    async def call_with_fallback(
        self,
        prompt: str,
        task: str,
        fallback: dict,
        temperature: Optional[float] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
    
        response = await self.call(
            prompt=prompt,
            task=task,
            temperature=temperature,
            use_cache=use_cache,
        )
    
        if response.success and response.content:
            return {
                **response.content,
                "model": response.model,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "duration": response.duration,
            }
    
        print(f"[LLM FALLBACK USED] {task}")
        return fallback
    
# =========================
# SINGLETON
# =========================
llm_service = LLMService()