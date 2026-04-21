import asyncio
import logging
from typing import Any
from langchain_openrouter import ChatOpenRouter

from app.ai_agents_v2.user_story_refinement.config import LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS

logger = logging.getLogger(__name__)

# Semaphore global pour limiter les appels simultanés
llm_semaphore = asyncio.Semaphore(3)  # Max 3 appels simultanés


class ControlledChatOpenRouter(ChatOpenRouter):
    """
    ChatOpenRouter avec contrôles de concurrence (semaphore).
    
    ✅ Basé sur la doc officielle
    ✅ Contrôle TOUS les appels LLM
    ✅ Permet à LangGraph de gérer la boucle ReAct
    """
    
    async def _agenerate(self, *args, **kwargs) -> Any:
        """Intercept tous les appels LLM pour appliquer le semaphore"""
        
        async with llm_semaphore:
            logger.debug("[LLM] Semaphore acquired, calling OpenRouter...")
            
            try:
                result = await super()._agenerate(*args, **kwargs)
                logger.debug("[LLM] ✓ Response received from OpenRouter")
                return result
            
            except Exception as e:
                logger.error(f"[LLM ERROR] OpenRouter call failed: {e}")
                raise


def create_llm(temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL) -> ControlledChatOpenRouter:
    """
    Factory pour créer une instance ChatOpenRouter contrôlée.

    Basé sur la doc officielle:
    https://python.langchain.com/docs/integrations/chat/openrouter
    """

    from app.core.config import settings

    if not settings.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not configured in .env")

    return ControlledChatOpenRouter(
        model=model,
        temperature=temperature,
        max_tokens=LLM_MAX_TOKENS,
        max_retries=2,
        api_key=settings.OPENROUTER_API_KEY,
    )