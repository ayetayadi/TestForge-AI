# import asyncio
# import logging

# from typing import Any, Optional
# from langchain_openrouter import ChatOpenRouter

# from app.ai_agents_v2.user_story_refinement.config import LLM_TEMPERATURE, LLM_MAX_TOKENS
# from app.core.config import settings

# logger = logging.getLogger(__name__)

# # Semaphore global pour limiter les appels simultanés
# llm_semaphore = asyncio.Semaphore(3)


# class ControlledChatOpenRouter(ChatOpenRouter):
#     """
#     ChatOpenRouter avec contrôles de concurrence (semaphore).
#     """
    
#     async def _agenerate(self, *args, **kwargs) -> Any:
#         async with llm_semaphore:
#             logger.debug("[LLM] Semaphore acquired, calling OpenRouter...")
#             try:
#                 result = await super()._agenerate(*args, **kwargs)
#                 logger.debug("[LLM] ✓ Response received from OpenRouter")
#                 return result
#             except Exception as e:
#                 logger.error(f"[LLM ERROR] OpenRouter call failed: {e}")
#                 raise


# def create_llm(
#     temperature: float = LLM_TEMPERATURE,
#     model: Optional[str] = None,
#     max_tokens: int = LLM_MAX_TOKENS
# ) -> ControlledChatOpenRouter:
#     """
#     Factory pour créer une instance ChatOpenRouter contrôlée.
    
#     Args:
#         temperature: Température (0.0-1.0)
#         model: Nom du modèle OpenRouter (ex: "openai/gpt-oss-120b")
#         max_tokens: Nombre max de tokens
#     """
#     if not settings.OPENROUTER_API_KEY:
#         raise ValueError("OPENROUTER_API_KEY not configured in .env")

#     # Utiliser le modèle passé en paramètre ou celui de la config
#     model_name = model or getattr(settings, "LLM_MODEL", "openai/gpt-oss-120b")

#     return ControlledChatOpenRouter(
#         model=model_name,
#         temperature=temperature,
#         max_tokens=max_tokens,
#         max_retries=2,
#         api_key=settings.OPENROUTER_API_KEY,
#     )


import asyncio
import logging
from typing import Any, Optional
from langchain_groq import ChatGroq  # ← Directement via langchain_groq
from app.ai_workflows.user_story_refinement.config import LLM_TEMPERATURE, LLM_MAX_TOKENS
from app.core.config import settings

logger = logging.getLogger(__name__)

# Semaphore global pour limiter les appels simultanés
llm_semaphore = asyncio.Semaphore(5)


class ControlledChatGroq(ChatGroq):
    """ChatGroq avec contrôles de concurrence."""
    
    async def _agenerate(self, *args, **kwargs) -> Any:
        async with llm_semaphore:
            logger.debug("[LLM] Semaphore acquired, calling Groq...")
            try:
                result = await super()._agenerate(*args, **kwargs)
                logger.debug("[LLM] ✓ Response received from Groq")
                return result
            except Exception as e:
                logger.error(f"[LLM ERROR] Groq call failed: {e}")
                raise
def create_llm(temperature: float = 0.3, model: str = "openai/gpt-oss-120b"):
    return ChatGroq(
        groq_api_key=settings.GROQ_API_KEY,
        model=model,
        temperature=temperature,
        max_tokens=LLM_MAX_TOKENS,
    )
# # # import asyncio
# # # import logging
# # # from typing import Any, Optional
# # # from langchain_openai import ChatOpenAI
# # # from app.core.config import settings

# # # logger = logging.getLogger(__name__)

# # # llm_semaphore = asyncio.Semaphore(5)


# # # class ControlledAtlasChat(ChatOpenAI):
# # #     """ChatOpenAI avec contrôles de concurrence pour Atlas Cloud."""
    
# # #     async def _agenerate(self, *args, **kwargs) -> Any:
# # #         async with llm_semaphore:
# # #             logger.debug("[LLM] Semaphore acquired, calling Atlas Cloud...")
# # #             try:
# # #                 result = await super()._agenerate(*args, **kwargs)
# # #                 logger.debug("[LLM] ✓ Response received from Atlas Cloud")
# # #                 return result
# # #             except Exception as e:
# # #                 logger.error(f"[LLM ERROR] Atlas Cloud call failed: {e}")
# # #                 raise


# # # def create_llm(
# # #     temperature: float = 0.3,
# # #     model: str = "openai/gpt-oss-120b",
# # #     max_tokens: int = 1500
# # # ) -> ControlledAtlasChat:
# # #     """
# # #     Factory pour créer une instance Atlas Cloud.
    
# # #     Args:
# # #         temperature: Température (0.0-1.0)
# # #         model: Nom du modèle (ex: "openai/gpt-oss-120b")
# # #         max_tokens: Nombre max de tokens
# # #     """
# # #     if not settings.ATLAS_API_KEY:
# # #         raise ValueError(
# # #             "ATLAS_API_KEY not configured in .env\n"
# # #             "Get your key at: https://www.atlascloud.ai"
# # #         )
    
# # #     base_url = getattr(settings, "ATLAS_BASE_URL", "https://api.atlascloud.ai/v1")
    
# # #     return ControlledAtlasChat(
# # #         model=model,
# # #         temperature=temperature,
# # #         max_tokens=max_tokens,
# # #         max_retries=2,
# # #         api_key=settings.ATLAS_API_KEY,
# # #         base_url=base_url,
# # #         timeout=60,
# # #     )


# # # app/llm/llm_control.py
# # import asyncio
# # import logging
# # from typing import Any, Optional
# # from langchain_openai import ChatOpenAI  # GitHub Models utilise API compatible OpenAI
# # from app.core.config import settings

# # logger = logging.getLogger(__name__)

# # llm_semaphore = asyncio.Semaphore(5)


# # class ControlledGitHubChat(ChatOpenAI):
# #     """ChatOpenAI avec contrôles de concurrence pour GitHub Models."""
    
# #     async def _agenerate(self, *args, **kwargs) -> Any:
# #         async with llm_semaphore:
# #             logger.debug("[LLM] Semaphore acquired, calling GitHub Models...")
# #             try:
# #                 result = await super()._agenerate(*args, **kwargs)
# #                 logger.debug("[LLM] ✓ Response received from GitHub Models")
# #                 return result
# #             except Exception as e:
# #                 logger.error(f"[LLM ERROR] GitHub Models call failed: {e}")
# #                 raise


# # def create_llm(
# #     temperature: float = 0.3,
# #     model: str = "gpt-4o",  # ou gpt-4o-mini, llama-3.3-70b
# #     max_tokens: int = 1500
# # ) -> ControlledGitHubChat:
# #     """
# #     Factory pour créer une instance GitHub Models.
    
# #     Modèles disponibles:
# #     - gpt-4o
# #     - gpt-4o-mini  
# #     - llama-3.3-70b
# #     - mistral-large
# #     - codestral
# #     """
# #     if not settings.GITHUB_TOKEN:
# #         raise ValueError(
# #             "GITHUB_TOKEN not configured in .env\n"
# #             "Get your GitHub token with Models access"
# #         )
    
# #     # URL de l'API GitHub Models
# #     base_url = "https://models.inference.ai.azure.com"
    
# #     return ControlledGitHubChat(
# #         model=model,
# #         temperature=temperature,
# #         max_tokens=max_tokens,
# #         max_retries=2,
# #         api_key=settings.GITHUB_TOKEN,
# #         base_url=base_url,
# #         timeout=60,
# #     )