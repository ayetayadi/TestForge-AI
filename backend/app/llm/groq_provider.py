import httpx
import json
import asyncio
import random

from langsmith import get_current_run_tree, traceable
from app.core.config import settings
from app.llm.base import LLMProvider


class GroqProvider(LLMProvider):

    def __init__(self, model: str):
        self.api_key = settings.GROQ_API_KEY
        self.model = model

        if not self.api_key:
            raise ValueError("GROQ_API_KEY is missing")

    # =========================
    # PAYLOAD
    # =========================
    def _build_payload(self, prompt: str, temperature: float) -> dict:
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a JSON-only responder. "
                        "Your output MUST be a single valid JSON object. "
                        "No markdown, no ```json fences, no preamble. "
                        "Start with { and end with }."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }

    # =========================
    # BACKOFF
    # =========================
    def _calc_wait(self, attempt: int, retry_after: float = None) -> float:
        if retry_after:
            return retry_after + random.uniform(0, 1)

        base = 2 ** attempt
        jitter = random.uniform(0, base * 0.3)
        return base + jitter

    # =========================
    # SYNC VERSION
    # =========================
    def generate(self, prompt: str, temperature: float = 0.0, retries: int = 5) -> dict:
        import time
        last_error = None

        for attempt in range(retries):
            try:
                response = httpx.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=self._build_payload(prompt, temperature),
                    timeout=120,
                )

                # RATE LIMIT
                if response.status_code == 429:
                    retry_after = float(response.headers.get("retry-after", 0))
                    wait = self._calc_wait(attempt, retry_after)
                    print(f"[Groq RATE LIMIT] Attempt {attempt+1}/{retries}. Waiting {wait:.1f}s...")
                    time.sleep(wait)
                    continue

                response.raise_for_status()

                content = response.json()["choices"][0]["message"]["content"]

                if not content:
                    raise ValueError("Groq returned empty content")

                parsed = json.loads(content)

                # META INFO
                parsed["_meta"] = {
                    "provider": "groq",
                    "model": self.model
                }

                print(f"[Groq SUCCESS] Attempt {attempt+1}")
                return parsed

            except json.JSONDecodeError as e:
                print(f"[Groq JSON ERROR] {e}")
                last_error = e

            except httpx.TimeoutException:
                print(f"[Groq TIMEOUT]")
                last_error = "Timeout"

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    continue
                print(f"[Groq HTTP ERROR] {e.response.status_code}")
                last_error = e

            except Exception as e:
                print(f"[Groq ERROR] {e}")
                last_error = e

            if attempt < retries - 1:
                wait = self._calc_wait(attempt)
                print(f"[Groq RETRY] Retrying in {wait:.1f}s...")
                time.sleep(wait)

        print(f"[Groq FAILED] After {retries} attempts. Last error: {last_error}")

        return {
            "llm_failed": True,
            "error": str(last_error) if last_error else "unknown"
        }

    # =========================
    # ASYNC VERSION
    # =========================
    @traceable(name="groq_api_call")
    async def generate_async(
        self, prompt: str, temperature: float = 0.0, retries: int = 5
    ) -> dict:
        last_error = None
    
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=self._build_payload(prompt, temperature),
                    )
    
                    # RATE LIMIT → retry avec backoff
                    if response.status_code == 429:
                        run = get_current_run_tree()
                        if run:
                            run.metadata["rate_limited"] = True
                            run.metadata["retry_after"] = response.headers.get("retry-after")
    
                        retry_after = float(response.headers.get("retry-after", 0))
                        wait = self._calc_wait(attempt, retry_after)
                        print(f"[Groq RATE LIMIT] Attempt {attempt+1}/{retries}. Waiting {wait:.1f}s...")
                        await asyncio.sleep(wait)
                        continue
    
                    response.raise_for_status()
    
                    content = response.json()["choices"][0]["message"]["content"]
                    if not content:
                        raise ValueError("Empty content")
    
                    parsed = json.loads(content)
                    parsed["_meta"] = {"provider": "groq", "model": self.model}
    
                    print(f"[Groq SUCCESS] Attempt {attempt+1}")
                    return parsed
    
            except json.JSONDecodeError as e:
                print(f"[Groq JSON ERROR] {e}")
                last_error = e
    
            except httpx.TimeoutException:
                print("[Groq TIMEOUT]")
                last_error = "Timeout"
    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    continue
                print(f"[Groq HTTP ERROR] {e.response.status_code}")
                last_error = e
    
            except Exception as e:
                print(f"[Groq ERROR] {e}")
                last_error = e
    
            # Backoff avant prochain essai
            if attempt < retries - 1:
                wait = self._calc_wait(attempt)
                print(f"[Groq RETRY] Waiting {wait:.1f}s...")
                await asyncio.sleep(wait)
    
        print(f"[Groq FAILED] After {retries} attempts")
        return {"llm_failed": True, "error": str(last_error) if last_error else "unknown"}