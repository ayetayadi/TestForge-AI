# ============================================================
# app/llm/base.py
# ============================================================
"""
Base class for LLM providers.

Support both:
- JSON generation (for parsing)
- Tool calling (for ReAct agents)
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List


class LLMProvider(ABC):
    """
    Abstract base for LLM providers.
    
    Must support:
    1. generate() - For simple JSON/text generation
    2. generate_with_tools() - For ReAct agents with tool calling
    """

    @abstractmethod
    def generate(self, prompt: str, temperature: float) -> str:
        """
        Generate simple text/JSON response.
        
        Args:
            prompt: User prompt
            temperature: Temperature (0.0-1.0)
            
        Returns:
            Generated text
        """
        pass

    @abstractmethod
    async def generate_async(
        self,
        prompt: str,
        temperature: float = 0.0,
        retries: int = 5
    ) -> Dict[str, Any]:
        """
        Async version of generate().
        
        Returns dict with content and metadata.
        """
        pass

    @abstractmethod
    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
        max_iterations: int = 10
    ) -> Dict[str, Any]:
        """
        Generate response with tool calling (for ReAct agents).
        
        Args:
            prompt: System + user prompt
            tools: List of tool definitions (JSON schema format)
            temperature: Temperature
            max_iterations: Max tool call iterations
            
        Returns:
            dict with:
                - final_response: Final text output
                - tool_calls: List of tool calls made
                - success: Whether succeeded
                - error: Error message if failed
        """
        pass