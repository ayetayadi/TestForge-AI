"""
Post-processing enrichment: Gherkin scenarios + test data.

Runs a single focused LLM call after the test case agent finishes —
no ReAct loop, no tool schema overhead, forced tool choice.
Fails gracefully: returns test cases unchanged if anything goes wrong.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from openai import OpenAI

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tc_gherkin")

_SYSTEM_PROMPT = """\
You are an expert BDD author and test data specialist.

For each test case:
1. Write a Gherkin Scenario block:
   - @tags on the line before Scenario:  (use tags from the test case)
   - "Scenario: <exact test case name>"
   - Map steps: navigation/preconditions → Given, user actions → When, assertions → Then/And
   - Keep steps atomic and implementation-independent
2. Generate test_data — concrete key/value pairs needed to execute the test:
   - Use realistic fake values (e.g. "user@example.com", "Pass@123", 99.99)
   - For Negative tests: include an invalid value that triggers the failure
   - Omit fields that are not relevant to this specific test

Return ALL test cases in one submit_gherkin call.
"""

_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_gherkin",
        "description": "Submit Gherkin scenarios and test data for every test case.",
        "parameters": {
            "type": "object",
            "properties": {
                "test_cases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Test case ID (e.g. TC-001)",
                            },
                            "gherkin_scenario": {
                                "type": "string",
                                "description": "Full Gherkin block: @tags + Scenario: + Given/When/Then steps",
                            },
                            "test_data": {
                                "type": "object",
                                "description": "Concrete test input values (key/value pairs)",
                            },
                        },
                        "required": ["id", "gherkin_scenario"],
                    },
                }
            },
            "required": ["test_cases"],
        },
    },
}


def _build_compact_input(test_cases: List[Dict]) -> List[Dict]:
    """Strip fields not needed for Gherkin generation to reduce input tokens."""
    return [
        {
            "id":        tc.get("id"),
            "name":      tc.get("name"),
            "test_type": tc.get("test_type"),
            "tags":      tc.get("tags") or [],
            "steps": [
                {
                    "description":     s.get("description", ""),
                    "expected_result": s.get("expected_result", ""),
                }
                for s in (tc.get("steps") or [])
            ],
        }
        for tc in test_cases
    ]


async def enrich_with_gherkin(
    test_cases: List[Dict[str, Any]],
    user_story: str,
    model: str = "openai/gpt-4o-mini",
) -> List[Dict[str, Any]]:
    """
    Add gherkin_scenario and test_data to each test case via a single LLM call.
    Returns the original list unchanged if the call fails or is skipped.
    """
    if not test_cases:
        return test_cases

    try:
        from app.core.config import settings
        api_key = settings.OPENROUTER_API_KEY
    except Exception:
        api_key = None

    if not api_key:
        logger.warning("[gherkin] OPENROUTER_API_KEY not set — skipping Gherkin enrichment")
        return test_cases

    tc_input = _build_compact_input(test_cases)
    user_content = (
        f"User Story: {user_story}\n\n"
        f"Test Cases ({len(tc_input)}):\n"
        + json.dumps(tc_input, ensure_ascii=False)
    )

    def _call() -> Dict[str, Any]:
        client = OpenAI(api_key=api_key, base_url=_OPENROUTER_BASE_URL)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_content},
            ],
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "function", "function": {"name": "submit_gherkin"}},
            temperature=0.2,
            max_tokens=4096,
        )
        tool_calls = resp.choices[0].message.tool_calls or []
        if not tool_calls:
            return {}
        return json.loads(tool_calls[0].function.arguments or "{}")

    try:
        import asyncio
        loop = asyncio.get_running_loop()
        args = await loop.run_in_executor(_EXECUTOR, _call)
    except Exception as exc:
        logger.warning("[gherkin] LLM call failed: %s — skipping enrichment", exc)
        return test_cases

    raw_items: List[Dict] = args.get("test_cases") or []
    gherkin_map: Dict[str, Dict] = {
        item["id"]: item
        for item in raw_items
        if isinstance(item, dict) and item.get("id")
    }

    enriched = []
    for tc in test_cases:
        g = gherkin_map.get(tc.get("id", ""))
        enriched.append({
            **tc,
            "gherkin_scenario": g.get("gherkin_scenario", "") if g else "",
            "test_data":        g.get("test_data", {})        if g else {},
        })

    matched = sum(1 for tc in test_cases if tc.get("id") in gherkin_map)
    logger.info("[gherkin] Enriched %d/%d test cases with Gherkin + test data", matched, len(test_cases))
    return enriched
