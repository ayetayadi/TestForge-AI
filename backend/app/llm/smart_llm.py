import re
import json
import asyncio
from app.llm.groq_provider import GroqProvider
from app.utils.common.llm_safety_utils import safe_json_parse

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

    def generate(self, prompt: str, temperature: float, retries: int = 5) -> dict:
        """
        Version synchrone avec retries améliorés.
        """
        response = self.provider.generate(prompt, temperature, retries=retries)
        
        # Si le provider a retourné une erreur
        if isinstance(response, dict) and response.get("llm_failed"):
            print("[LLM FAILED] Provider returned error")
            fallback = FALLBACKS.get(self.task, FALLBACKS["analysis"]).copy()
            return fallback
        
        # Si le provider a retourné un dict valide
        if isinstance(response, dict):
            response["llm_failed"] = False
            return response
        
        # Sinon, essayer de parser
        if isinstance(response, str):
            parsed = safe_json_parse(response, None)
            if parsed:
                parsed["llm_failed"] = False
                return parsed
        
        # Fallback final
        print("[LLM FAILED] No valid response")
        fallback = FALLBACKS.get(self.task, FALLBACKS["analysis"]).copy()
        return fallback

    async def generate_async(self, prompt: str, temperature: float, retries: int = 5) -> dict:
        """
        Version asynchrone pour les nodes asyncio.
        """
        response = await self.provider.generate_async(prompt, temperature, retries=retries)
        
        if isinstance(response, dict) and response.get("llm_failed"):
            print("[LLM FAILED] Provider returned error")
            fallback = FALLBACKS.get(self.task, FALLBACKS["analysis"]).copy()
            return fallback
        
        if isinstance(response, dict):
            response["llm_failed"] = False
            return response
        
        fallback = FALLBACKS.get(self.task, FALLBACKS["analysis"]).copy()
        return fallback