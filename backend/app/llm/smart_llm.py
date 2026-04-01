import re
import json
from time import time

from app.llm.groq_provider import GroqProvider
from app.utils.common.llm_safety_utils import safe_json_parse
from app.llm.shared_rate_limiter import get_rate_limiter

FALLBACKS = {
    "analysis": {
        "llm_score": 0.3,
        "llm_issues": ["LLM failed"],
        "llm_suggestions": [],
        "llm_failed": True,
    },
    "refinement": {
        "improved_story": None,
        "acceptance_criteria": [],
        "llm_failed": True,
    },
    "ac_repair": {
        "acceptance_criteria": [],
        "llm_failed": True,
    },
}


class SmartLLM:

    def __init__(self, task: str = "default"):
        self.task = task

        if task == "analysis":
            model = "openai/gpt-oss-120b"
        elif task == "refinement":
            model = "openai/gpt-oss-120b"
        elif task == "ac_repair":
            model = "openai/gpt-oss-120b"
        else:
            model = "openai/gpt-oss-120b"

        self.provider = GroqProvider(model=model)
        self.rate_limiter = get_rate_limiter()

    def generate(self, prompt: str, temperature: float, retries: int = 3) -> dict:

        """Génère une réponse avec rate limiting."""
        
        # Vérifie le rate limit AVANT d'essayer
        can_make, wait_time = self.rate_limiter.can_make_request()
        if not can_make:
            print(f"[RATE LIMIT] Attente globale de {wait_time:.1f}s avant de commencer")
            time.sleep(wait_time)
            
        last_raw = None
        last_error = None

        for attempt in range(retries):
            try:
                print(f"[LLM] Groq attempt {attempt + 1}")
                response = self.provider.generate(prompt, temperature)

                # Guard against None/empty responses from provider
                if response is None or response == "":
                    last_error = "Empty response from provider"
                    continue

                last_raw = response
                print(f"\n[LLM RAW TEXT] {str(response)[:500]}")

                # If provider already returned a dict (after your fix), use it directly
                if isinstance(response, dict):
                    response["llm_failed"] = False
                    print("[LLM SUCCESS] Groq")
                    return response

                # Otherwise parse string to dict
                parsed = safe_json_parse(response, None)

                if parsed is not None:
                    print("[LLM SUCCESS] Groq")
                    parsed["llm_failed"] = False
                    return parsed

                print("[LLM INVALID JSON] retrying...")
                print(f"[LLM RAW RESPONSE] {str(response)[:500]}")

            except Exception as e:
                last_error = str(e)
                print(f"[LLM ERROR] attempt {attempt + 1}: {e}")

        print("[LLM FAILED]")
        if last_raw:
            print(f"[LLM LAST RAW] {str(last_raw)[:300]}")
        if last_error:
            print(f"[LLM LAST ERROR] {last_error}")

        fallback = FALLBACKS.get(self.task, FALLBACKS["analysis"]).copy()
        return fallback