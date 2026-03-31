import requests
import json
from app.core.config import settings
from app.llm.base import LLMProvider


class GroqProvider(LLMProvider):

    def __init__(self, model: str = "openai/gpt-oss-120b"):
        self.api_key = settings.GROQ_API_KEY
        self.model = model

        if not self.api_key:
            raise ValueError("GROQ_API_KEY is missing")

    def generate(self, prompt: str, temperature: float = 0.0) -> dict:
        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
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
                timeout=120,
            )

            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]

            if not content:
                print(f"[Groq] Empty content returned for model={self.model}")
                raise ValueError("Groq returned empty content")

            parsed = json.loads(content)
            return parsed

        except json.JSONDecodeError as e:
            print(f"[Groq JSON ERROR] model={self.model} error={e}")
            print(f"[Groq RAW] {content[:500] if content else 'None'}")
            raise

        except requests.exceptions.Timeout:
            print(f"[Groq TIMEOUT] model={self.model}")
            raise

        except requests.exceptions.HTTPError as e:
            print(f"[Groq HTTP ERROR] {e.response.status_code}: {e.response.text[:300]}")
            raise

        except Exception as e:
            print(f"[Groq ERROR] {e}")
            raise