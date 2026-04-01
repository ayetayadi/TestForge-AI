import requests
import json
import time
from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.shared_rate_limiter import get_rate_limiter


class GroqProvider(LLMProvider):

    def __init__(self, model: str = "openai/gpt-oss-120b"):
        self.api_key = settings.GROQ_API_KEY
        self.model = model
        self.rate_limiter = get_rate_limiter()  # ← Déjà là, c'est bon
        print(f"[GroqProvider] Initialized with model={model}")

        if not self.api_key:
            raise ValueError("GROQ_API_KEY is missing")

    def generate(self, prompt: str, temperature: float = 0.0) -> dict:
        """Génère une réponse avec rate limiting automatique."""
        
        max_wait_attempts = 5
        
        for attempt in range(max_wait_attempts):
            try:
                can_make, wait_time = self.rate_limiter.can_make_request()
                
                if not can_make:
                    print(f"[RATE LIMIT] Attente de {wait_time:.1f}s avant requête (tentative {attempt+1}/{max_wait_attempts})")
                    time.sleep(wait_time + 0.5)
                    continue
                
                self.rate_limiter.record_request()
                return self._call_groq_api(prompt, temperature)
                
            except Exception as e:
                if "429" in str(e) or "rate limit" in str(e).lower():
                    print(f"[RATE LIMIT] Erreur 429, réessai {attempt+1}/{max_wait_attempts}")
                    time.sleep(2 ** attempt)
                    continue
                raise
        
        raise Exception(f"Rate limit: échec après {max_wait_attempts} tentatives")
    
    def _call_groq_api(self, prompt: str, temperature: float) -> dict:
        """Appel réel à l'API Groq."""
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
            print(f"[Groq RAW] {content[:500] if 'content' in locals() else 'None'}")
            raise

        except requests.exceptions.Timeout:
            print(f"[Groq TIMEOUT] model={self.model}")
            raise

        except requests.exceptions.HTTPError as e:
            print(f"[Groq HTTP ERROR] {e.response.status_code}: {e.response.text[:300]}")
            if e.response.status_code == 429:
                raise Exception(f"429 rate limit: {e.response.text[:200]}")
            raise

        except Exception as e:
            print(f"[Groq ERROR] {e}")
            raise