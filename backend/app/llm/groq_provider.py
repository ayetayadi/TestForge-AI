import httpx
import json
import asyncio
import random
from app.core.config import settings
from app.llm.base import LLMProvider


class GroqProvider(LLMProvider):

    def __init__(self, model: str = "openai/gpt-oss-120b"):
        self.api_key = settings.GROQ_API_KEY
        self.model = model
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is missing")

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

    def _calc_wait(self, attempt: int, retry_after: float = None) -> float:
        """Exponentiel + jitter pour éviter le thundering herd."""
        if retry_after:
            return retry_after + random.uniform(0, 1)
        base = 2 ** attempt  # 1, 2, 4, 8, 16...
        jitter = random.uniform(0, base * 0.3)
        return base + jitter

    # ─── SYNC (pour Celery) ───────────────────────────────────────
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
        return {"llm_failed": True}

    # ─── ASYNC (pour FastAPI / graph.ainvoke) ─────────────────────
    async def generate_async(self, prompt: str, temperature: float = 0.0, retries: int = 5) -> dict:
        last_error = None

        async with httpx.AsyncClient(timeout=120) as client:
            for attempt in range(retries):
                try:
                    response = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=self._build_payload(prompt, temperature),
                    )

                    if response.status_code == 429:
                        retry_after = float(response.headers.get("retry-after", 0))
                        wait = self._calc_wait(attempt, retry_after)
                        print(f"[Groq RATE LIMIT] Attempt {attempt+1}/{retries}. Waiting {wait:.1f}s...")
                        await asyncio.sleep(wait)
                        continue

                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]

                    if not content:
                        raise ValueError("Groq returned empty content")

                    parsed = json.loads(content)
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
                    await asyncio.sleep(wait)

        print(f"[Groq FAILED] After {retries} attempts. Last error: {last_error}")
        return {"llm_failed": True}