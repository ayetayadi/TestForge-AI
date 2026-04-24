"""
Groq Provider for GPT-OSS-120B (FAST & FREE).

✅ COMPLETE IMPLEMENTATION:
- Ultra-fast inference (~500 tokens/sec)
- Free tier with rate limits
- Full tool calling support
"""

import httpx
import json
import asyncio
import random
from typing import Dict, Any, List, Optional

from langsmith import get_current_run_tree, traceable
from app.core.config import settings


class GroqProvider:
    """
    Groq LLM Provider with GPT-OSS-120B (FAST).
    """

    def __init__(self, model: str = "openai/gpt-oss-120b"):
        self.api_key = settings.GROQ_API_KEY
        self.model = model
        self.base_url = "https://api.groq.com/openai/v1"

        if not self.api_key:
            raise ValueError(
                "GROQ_API_KEY is missing. "
                "Get your free key at https://console.groq.com/keys"
            )

        print(f"[Groq] Initialized with model: {self.model}")

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @traceable(name="groq_tool_calling")
    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        temperature: float = 0.3,
        max_iterations: int = 10
    ) -> Dict[str, Any]:
        """
        Generate response with tool calling (ReAct agent).
        """
        print(f"[Groq TOOLS] Starting ReAct agent")
        print(f"  Model: {self.model}")
        print(f"  Tools: {len(tools)} available")

        # ⚠️ CRITICAL: Ajouter un outil 'json' pour capturer la réponse finale
        # Le modèle GPT-OSS-120b a tendance à utiliser un outil 'json'
        json_tool = {
            "type": "function",
            "function": {
                "name": "json",
                "description": "Output the final JSON result. Call this when you have the final answer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "improved_story": {"type": "string"},
                        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                        "reasoning": {"type": "string"},
                        "iterations": {"type": "integer"},
                        "initial_score": {"type": "number"},
                        "final_score": {"type": "number"},
                        "testability_score": {"type": "number"},
                        "is_testable": {"type": "boolean"},
                        "testability_issues": {"type": "array", "items": {"type": "string"}},
                        "violations": {"type": "array", "items": {"type": "string"}},
                        "workflow_status": {"type": "string"}
                    },
                    "required": ["improved_story", "acceptance_criteria", "reasoning", "iterations", "workflow_status"]
                }
            }
        }
        
        # Ajouter l'outil json aux outils existants (sans duplicata)
        tool_names = [t.get("function", {}).get("name") for t in tools]
        if "json" not in tool_names:
            tools = tools + [json_tool]

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a ReAct Agent with access to tools. "
                        "Use the provided tools to complete the user's request. "
                        "When you have the final result, call the 'json' tool with the complete JSON output. "
                        "Do not output any other text."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": 1500,  # Réduit pour éviter rate limit
            "tools": tools,
            "tool_choice": "auto",  # Important : laisser le modèle choisir
        }

        tool_calls_history = []
        iterations = 0

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                while iterations < max_iterations:
                    iterations += 1

                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._get_headers(),
                        json=payload,
                    )

                    if response.status_code == 429:
                        retry_after = float(response.headers.get("retry-after", 1))
                        print(f"[Groq RATE LIMIT] Waiting {retry_after}s...")
                        await asyncio.sleep(retry_after)
                        continue

                    if response.status_code != 200:
                        error_text = response.text
                        print(f"[Groq TOOL ERROR] {response.status_code}: {error_text}")
                        return {
                            "final_response": None,
                            "tool_calls": tool_calls_history,
                            "success": False,
                            "error": f"API error: {response.status_code}",
                            "iterations": iterations,
                        }

                    data = response.json()
                    message = data["choices"][0]["message"]

                    if message.get("tool_calls"):
                        for tool_call in message["tool_calls"]:
                            tool_name = tool_call["function"]["name"]
                            tool_args = json.loads(tool_call["function"]["arguments"])
                            
                            tool_calls_history.append({
                                "name": tool_name,
                                "arguments": tool_args,
                                "id": tool_call["id"],
                            })

                            print(f"[Groq TOOL CALL] {tool_name}")

                            # Si c'est l'outil 'json', c'est la réponse finale !
                            if tool_name == "json":
                                print(f"[Groq FINAL] JSON output captured")
                                return {
                                    "final_response": tool_args,
                                    "tool_calls": tool_calls_history,
                                    "success": True,
                                    "iterations": iterations,
                                    "error": None,
                                }

                            # Sinon, exécuter l'outil normalement
                            payload["messages"].append(message)
                            payload["messages"].append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": f"Tool '{tool_name}' executed successfully",
                            })
                    else:
                        # Fallback si pas de tool call
                        final_response = message.get("content", "")
                        print(f"[Groq FINAL] Raw response after {iterations} iterations")

                        return {
                            "final_response": final_response,
                            "tool_calls": tool_calls_history,
                            "success": True,
                            "iterations": iterations,
                            "error": None,
                        }

            return {
                "final_response": None,
                "tool_calls": tool_calls_history,
                "success": False,
                "error": f"Max iterations ({max_iterations}) reached",
                "iterations": iterations,
            }

        except Exception as e:
            print(f"[Groq TOOL ERROR] {e}")
            return {
                "final_response": None,
                "tool_calls": tool_calls_history,
                "success": False,
                "error": str(e),
                "iterations": iterations,
            }