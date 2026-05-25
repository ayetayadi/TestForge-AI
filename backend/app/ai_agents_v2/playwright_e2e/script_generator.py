import logging
from typing import List, Dict, Any, Optional

from langchain_core.messages import SystemMessage, HumanMessage

from app.llm.llm_control import create_llm_for_model
from .prompts import (
    SCRIPT_GENERATOR_SYSTEM, SCRIPT_GENERATOR_USER,
    SCRIPT_GENERATOR_SYSTEM_WITH_DOM, SCRIPT_GENERATOR_USER_WITH_DOM,
    SCRIPT_GENERATOR_SYSTEM_MULTIPAGE, SCRIPT_GENERATOR_USER_MULTIPAGE,
)
from .config import PLACEHOLDER_PREFIX

logger = logging.getLogger(__name__)

LLM_MODEL = "llama-3.3-70b-versatile"
LLM_TEMPERATURE = 0.3
LLM_MAX_TOKENS = 2000  # increased: multi-page context requires richer output

class ScriptGeneratorService:
    """
    LLM classique — génère un Script v1 avec placeholders [TESTFORGEAI: ...]
    à partir de cas de test. Pas de boucle, pas d'outils.
    """

    def __init__(self):
        logger.info("ScriptGeneratorService initialized")

    async def generate(
        self,
        test_cases: List[Dict[str, Any]],
        dom_snapshot: Optional[str] = None,
        app_url: Optional[str] = None,
        page_snapshots: Optional[Dict[str, str]] = None,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a TypeScript Playwright v1 script from test cases.

        Priority order for DOM context:
          1. page_snapshots (multi-page dict)  → SCRIPT_GENERATOR_SYSTEM_MULTIPAGE
          2. dom_snapshot (single legacy str)   → SCRIPT_GENERATOR_SYSTEM_WITH_DOM
          3. Neither                            → blind generation with placeholders only
        """
        from .config import APP_BASE_URL
        effective_url = app_url or APP_BASE_URL
        effective_model = model_id or LLM_MODEL

        # Normalise: legacy single snapshot → page_snapshots dict
        if dom_snapshot and not page_snapshots:
            page_snapshots = {"landing": dom_snapshot}

        mode = (
            f"multi-page ({len(page_snapshots)} pages)" if page_snapshots
            else "blind — no DOM"
        )
        logger.info(
            f"Generating TypeScript Playwright script for {len(test_cases)} test case(s) "
            f"[{mode}], url={effective_url}, model={effective_model}"
        )

        formatted_cases = self._format_test_cases(test_cases)

        if page_snapshots:
            messages = self._build_multipage_messages(page_snapshots, formatted_cases, effective_url)
        else:
            messages = [
                SystemMessage(content=SCRIPT_GENERATOR_SYSTEM),
                HumanMessage(content=SCRIPT_GENERATOR_USER.format(
                    test_cases=formatted_cases,
                    placeholder_prefix=PLACEHOLDER_PREFIX,
                    app_url=effective_url,
                )),
            ]

        llm = create_llm_for_model(effective_model, LLM_TEMPERATURE, LLM_MAX_TOKENS)

        try:
            response = await llm.ainvoke(messages)
            script_v1 = self._strip_markdown_fences(response.content.strip())
            placeholder_count = script_v1.count(f"[{PLACEHOLDER_PREFIX}:")

            logger.info(
                f"Script generated [{mode}] — {placeholder_count} placeholder(s) remaining"
            )

            return {
                "script_v1": script_v1,
                "placeholder_count": placeholder_count,
                "model_used": effective_model,
                "status": "generated",
                "language": "typescript",
                "generation_mode": mode,
                "warning": (
                    f"Script contains {placeholder_count} placeholder locator(s). "
                    "Click 'Run Test' to resolve them against the live application."
                ) if placeholder_count > 0 else None,
            }

        except Exception as e:
            logger.error(f"Script generation failed: {e}", exc_info=True)
            return {
                "script_v1": "",
                "placeholder_count": 0,
                "model_used": effective_model,
                "status": "error",
                "error": str(e),
            }

    def _build_multipage_messages(
        self,
        page_snapshots: Dict[str, str],
        formatted_cases: str,
        effective_url: str,
    ) -> list:
        """
        Build LLM messages that include a formatted multi-page DOM section.
        Each page snapshot is capped at 2000 chars to stay within token budget.
        """
        sections: List[str] = []
        for label, snapshot in page_snapshots.items():
            heading = label.upper().replace("_", " ")
            sections.append(f"--- PAGE: {heading} ---\n{snapshot[:6000]}")
        page_snapshots_section = "\n\n".join(sections)

        return [
            SystemMessage(content=SCRIPT_GENERATOR_SYSTEM_MULTIPAGE),
            HumanMessage(content=SCRIPT_GENERATOR_USER_MULTIPAGE.format(
                app_url=effective_url,
                page_snapshots_section=page_snapshots_section,
                test_cases=formatted_cases,
                placeholder_prefix=PLACEHOLDER_PREFIX,
            )),
        ]

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