import logging
from typing import List, Dict, Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.llm.llm_control import create_llm
from .prompts import SCRIPT_GENERATOR_SYSTEM, SCRIPT_GENERATOR_USER
from .config import LLM_MODEL, LLM_TEMPERATURE, PLACEHOLDER_PREFIX

logger = logging.getLogger(__name__)


class ScriptGeneratorService:
    """
    LLM classique — génère un Script v1 avec placeholders [TESTFORGEAI: ...]
    à partir de cas de test. Pas de boucle, pas d'outils.
    """

    def __init__(self):
        self.llm = create_llm(temperature=LLM_TEMPERATURE)
        logger.info("ScriptGeneratorService initialized")

    async def generate(self, test_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Génère un Script Playwright TypeScript v1 à partir des cas de test.

        Args:
            test_cases: liste de dicts avec 'title', 'steps', 'expected_result'

        Returns:
            dict avec 'script_v1' (str), 'placeholder_count' (int), 'model_used' (str)
        """
        logger.info(f"Generating TypeScript Playwright script for {len(test_cases)} test case(s)")

        formatted_cases = self._format_test_cases(test_cases)

        messages = [
            SystemMessage(content=SCRIPT_GENERATOR_SYSTEM),
            HumanMessage(content=SCRIPT_GENERATOR_USER.format(
                test_cases=formatted_cases,
                placeholder_prefix=PLACEHOLDER_PREFIX,
            )),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            script_v1 = response.content.strip()

            script_v1 = self._strip_markdown_fences(script_v1)
            placeholder_count = script_v1.count(f"[{PLACEHOLDER_PREFIX}:")

            logger.info(f"TypeScript Playwright script generated — {placeholder_count} placeholder(s)")

            return {
                "script_v1": script_v1,
                "placeholder_count": placeholder_count,
                "model_used": LLM_MODEL,
                "status": "generated",
                "language": "typescript",
                "warning": (
                    f"Script contains {placeholder_count} placeholder locators. "
                    "Click 'Run Test' to resolve them against the real application."
                ) if placeholder_count > 0 else None,
            }

        except Exception as e:
            logger.error(f"Script generation failed: {e}", exc_info=True)
            return {
                "script_v1": "",
                "placeholder_count": 0,
                "model_used": LLM_MODEL,
                "status": "error",
                "error": str(e),
            }

    def _format_test_cases(self, test_cases: List[Dict[str, Any]]) -> str:
        lines = []
        for i, tc in enumerate(test_cases, 1):
            priority = tc.get("priority", "")
            title = tc.get("title", "Untitled")
            lines.append(f"Test Case {i}: {title}" + (f" [Priority: {priority}]" if priority else ""))

            if tc.get("description"):
                lines.append(f"  Description: {tc['description']}")

            tags = tc.get("tags") or []
            if tags:
                lines.append(f"  Tags: {', '.join(tags)}")

            preconditions = tc.get("preconditions") or []
            if preconditions:
                lines.append("  // PRECONDITIONS (à vérifier avant le test):")
                for p in preconditions:
                    lines.append(f"  // - {p}")

            if tc.get("gherkin_source"):
                lines.append("  Gherkin Scenario:")
                for gline in tc["gherkin_source"].splitlines():
                    lines.append(f"    {gline}")
            else:
                steps = tc.get("steps") or []
                if steps:
                    lines.append("  Steps:")
                    for step in steps:
                        if isinstance(step, dict):
                            action = step.get("action", "")
                            expected = step.get("expected", "")
                            order = step.get("order", "")
                            lines.append(f"    {order}. {action}" + (f" → {expected}" if expected else ""))
                        else:
                            lines.append(f"    - {step}")

            expected_results = tc.get("expected_results") or []
            if expected_results:
                lines.append("  Expected Results:")
                for er in expected_results:
                    lines.append(f"    - {er}")

            test_data = tc.get("test_data") or {}
            if test_data:
                lines.append("  Test Data:")
                for k, v in test_data.items():
                    lines.append(f"    {k}: {v}")

            locators = tc.get("locators") or []
            if locators:
                lines.append("  Known Locators:")
                for loc in locators:
                    name = loc.get("name", "")
                    selector = loc.get("selector", "")
                    reliability = loc.get("reliability", "")
                    lines.append(f"    {name}: {selector}" + (f" (reliability: {reliability})" if reliability else ""))

            postconditions = tc.get("postconditions") or []
            if postconditions:
                lines.append("  Postconditions:")
                for p in postconditions:
                    lines.append(f"    - {p}")

            lines.append("")
        return "\n".join(lines)

    def _strip_markdown_fences(self, text: str) -> str:
        """Remove ```typescript ... ``` fences if LLM added them."""
        if text.startswith("```"):
            lines = text.splitlines()
            lines = [l for l in lines if not l.strip().startswith("```")]
            return "\n".join(lines).strip()
        return text


# ============================================================
# SINGLETON
# ============================================================

_service_instance = None


def get_script_generator() -> ScriptGeneratorService:
    global _service_instance
    if _service_instance is None:
        _service_instance = ScriptGeneratorService()
    return _service_instance