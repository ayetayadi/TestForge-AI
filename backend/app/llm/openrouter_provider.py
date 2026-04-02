import requests
import json
from app.core.config import settings
from app.llm.base import LLMProvider


class OpenRouterProvider(LLMProvider):

    def __init__(self, model: str):
        self.api_key = settings.OPENROUTER_API_KEY
        self.model = model

        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is missing")

    def generate(self, prompt: str, temperature: float) -> dict:
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a JSON-only responder. "
                                "Your output MUST be a single valid JSON object. "
                                "No markdown, no ```json fences, no preamble, no text after the JSON. "
                                "Start with { and end with }."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": 4096,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )

            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]

            if not content:
                print(f"[OpenRouter] Empty content returned for model={self.model}")
                raise ValueError("OpenRouter returned empty content")

            # Parse JSON here so callers get a dict directly
            parsed = json.loads(content)
            return parsed

        except json.JSONDecodeError as e:
            print(f"[OpenRouter JSON ERROR] model={self.model} error={e}")
            print(f"[OpenRouter RAW] {content[:500] if content else 'None'}")
            raise

        except requests.exceptions.Timeout:
            print(f"[OpenRouter TIMEOUT] model={self.model}")
            raise

        except Exception as e:
            print(f"[OpenRouter ERROR] {e}")
            raise