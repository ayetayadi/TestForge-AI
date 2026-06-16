"""
Observability: Langfuse v4 tracing + DeepEval LLM-as-judge evaluation.

Langfuse v4 API used here
--------------------------
  from langfuse import observe          # @observe decorator
  from langfuse import get_client       # singleton client (auto-created from env vars)
  from langfuse.langchain import CallbackHandler  # LangChain callback

Inside an @observe-decorated function:
  client = get_client()
  client.update_current_span(input={...}, output={...}, metadata={...})
  trace_id = client.get_current_trace_id()

Scoring a finished trace:
  client.create_score(trace_id=trace_id, name="metric", value=0.8, comment="reason")

Usage in the codebase
---------------------
Tracing a pipeline:
    from langfuse import observe
    from langfuse import get_client
    from app.core.observability import get_trace_callback, fire_evaluation

    @observe(name="my_pipeline")
    async def run(self, ...):
        get_client().update_current_span(input={...})
        ...
        get_client().update_current_span(output={...})
        trace_id = get_client().get_current_trace_id()
        asyncio.create_task(fire_evaluation("user_story_quality", original, improved, trace_id))

LangChain LLM tracing (inside an @observe span):
    cb = get_trace_callback()
    config = {"callbacks": [cb]} if cb else {}
    await llm.ainvoke(prompt, config=config)
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# State flags
# ──────────────────────────────────────────────────────────────

_langfuse_enabled = False
_deepeval_configured = False


# ──────────────────────────────────────────────────────────────
# Langfuse
# ──────────────────────────────────────────────────────────────

def init_langfuse(public_key: str, secret_key: str, host: str) -> None:
    """
    Verify Langfuse connectivity and mark the integration as enabled.

    env vars (LANGFUSE_PUBLIC_KEY / SECRET_KEY / HOST) must already be in
    os.environ at this point — load_dotenv() at the top of main.py ensures
    they are set before any module importing langfuse is loaded, so langfuse
    auto-initialises its singleton with the correct credentials.
    """
    global _langfuse_enabled
    try:
        from langfuse import get_client
        ok = get_client().auth_check()
        if ok:
            _langfuse_enabled = True
            logger.info("[LANGFUSE] Auth OK — tracing enabled (host=%s)", host)
        else:
            logger.warning("[LANGFUSE] Auth failed — tracing disabled")
    except Exception as exc:
        logger.warning("[LANGFUSE] Init failed: %s", exc)


def is_langfuse_enabled() -> bool:
    return _langfuse_enabled


def get_trace_callback():
    """
    Return a Langfuse LangChain CallbackHandler that auto-inherits the current
    OpenTelemetry span context (set by @observe), so LLM calls appear nested
    inside their parent trace in the Langfuse UI.
    Returns None when Langfuse is not configured.
    """
    if not _langfuse_enabled:
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception as exc:
        logger.debug("[LANGFUSE] Callback creation skipped: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────
# DeepEval: init + Groq-backed evaluation model
# ──────────────────────────────────────────────────────────────

_groq_eval_model = None


def init_deepeval() -> None:
    """
    Validate that DeepEval can be imported and at least one Groq key is
    available for the eval model. Optionally registers the Confident AI
    API key so scores appear in the DeepEval cloud dashboard.
    """
    global _deepeval_configured
    try:
        import deepeval  # noqa: F401 — just verifying import
        from app.llm.llm_control import _GROQ_KEYS
        from app.core.config import settings

        if not _GROQ_KEYS:
            logger.warning("[DEEPEVAL] No Groq keys in pool — evaluation disabled")
            return

        # Register Confident AI cloud key if provided
        if settings.DEEPEVAL_API_KEY:
            import os
            os.environ.setdefault("DEEPEVAL_API_KEY", settings.DEEPEVAL_API_KEY)
            logger.info("[DEEPEVAL] Confident AI cloud key configured")

        _deepeval_configured = True
        logger.info(
            "[DEEPEVAL] Ready — eval model: groq/openai/gpt-oss-120b "
            "(%d key(s) available)", len(_GROQ_KEYS)
        )
    except ImportError:
        logger.warning("[DEEPEVAL] Package not installed — evaluation disabled")
    except Exception as exc:
        logger.warning("[DEEPEVAL] Init failed: %s", exc)


def is_deepeval_configured() -> bool:
    return _deepeval_configured


def _get_groq_eval_model():
    """
    Lazily build a DeepEvalBaseLLM subclass that routes metric inference
    through the project's ChatGroq key pool instead of OpenAI.
    Uses the first available key from the pool.
    """
    global _groq_eval_model
    if _groq_eval_model is not None:
        return _groq_eval_model

    from deepeval.models.base_model import DeepEvalBaseLLM
    from langchain_groq import ChatGroq
    from app.llm.llm_control import _GROQ_KEYS

    # Pick the first key in the pool (pool is already filtered to non-empty values)
    eval_key = _GROQ_KEYS[0]

    class _GroqEvalModel(DeepEvalBaseLLM):
        def __init__(self):
            self._chat = ChatGroq(
                groq_api_key=eval_key,
                model="openai/gpt-oss-120b",
                temperature=0.0,
                max_tokens=1024,
            )

        def load_model(self):
            return self._chat

        def generate(self, prompt: str, schema=None) -> str:
            return self._chat.invoke(prompt).content

        async def a_generate(self, prompt: str, schema=None) -> str:
            response = await self._chat.ainvoke(prompt)
            return response.content

        def get_model_name(self) -> str:
            return "groq/openai/gpt-oss-120b"

    _groq_eval_model = _GroqEvalModel()
    return _groq_eval_model


# ──────────────────────────────────────────────────────────────
# DeepEval metric factories
# ──────────────────────────────────────────────────────────────

def _make_user_story_metric():
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    return GEval(
        name="user_story_quality",
        criteria=(
            "Evaluate whether ACTUAL_OUTPUT (the improved story) is genuinely better "
            "than INPUT (the original story). Award a high score when: "
            "(1) it follows 'As a [role], I want [feature], so that [benefit]' format, "
            "(2) vague terms (quickly, easily, seamless, etc.) are replaced with "
            "measurable conditions, "
            "(3) at least 2 testable acceptance criteria are present with action verbs "
            "and measurable outcomes (e.g. 'within 2s', 'minimum 6 characters'), "
            "(4) INVEST principles are respected — Independent, Negotiable, Valuable, "
            "Estimable, Small, Testable, "
            "(5) the actor/role and intent of the original story are preserved. "
            "Score 1.0 if all criteria are met, 0.0 if no meaningful improvement."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=_get_groq_eval_model(),
        threshold=0.5,
        async_mode=False,
    )


def _make_playwright_metric():
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    return GEval(
        name="playwright_script_quality",
        criteria=(
            "Evaluate ACTUAL_OUTPUT (a generated Playwright TypeScript test script). "
            "Score high when: "
            "(1) the script has valid TypeScript and proper Playwright imports, "
            "(2) zero unresolved [PLACEHOLDER: ...] tokens remain in the script, "
            "(3) locators use recommended Playwright selectors "
            "(getByRole, getByLabel, getByPlaceholder, getByText, etc.), "
            "(4) meaningful assertions are present (expect(...).toBeVisible(), "
            "toHaveText(), toHaveValue(), etc.), "
            "(5) the test actions match the INPUT (test case description) faithfully. "
            "Score 1.0 if complete and correct, 0.0 if broken or still has placeholders."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=_get_groq_eval_model(),
        threshold=0.5,
        async_mode=False,
    )


def _make_test_case_metric():
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    return GEval(
        name="test_case_quality",
        criteria=(
            "Evaluate ACTUAL_OUTPUT (generated Gherkin test cases) against INPUT "
            "(the user story and acceptance criteria). Score high when: "
            "(1) each scenario follows valid Gherkin syntax "
            "(Given/When/Then with concrete steps), "
            "(2) at least 80% of acceptance criteria from INPUT are covered by a scenario, "
            "(3) steps are specific and directly testable — no vague verbs like 'verify', "
            "'check', or 'ensure' without a measurable outcome, "
            "(4) test data values (usernames, emails, amounts) are realistic and explicit, "
            "(5) positive, negative, and/or boundary scenarios are present as appropriate "
            "for the story. "
            "Score 1.0 if all criteria are met, 0.0 if Gherkin is missing or ACs uncovered."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=_get_groq_eval_model(),
        threshold=0.5,
        async_mode=False,
    )


_METRIC_FACTORIES = {
    "user_story_quality":    _make_user_story_metric,
    "playwright_script_quality": _make_playwright_metric,
    "test_case_quality":     _make_test_case_metric,
}


# ──────────────────────────────────────────────────────────────
# Public API: fire-and-forget evaluation
# ──────────────────────────────────────────────────────────────

async def fire_evaluation(
    metric: str,
    input_text: str,
    output_text: str,
    trace_id: Optional[str],
) -> None:
    """
    Run a DeepEval GEval metric in a thread pool (non-blocking) and push
    the resulting score to the Langfuse trace identified by trace_id.

    Designed to be launched with asyncio.create_task() so it never blocks
    the main pipeline response.

    Args:
        metric:      'user_story_quality' | 'playwright_script_quality' | 'test_case_quality'
        input_text:  Original input (story + ACs, test case description, etc.)
        output_text: Generated output (improved story, Playwright script, Gherkin TCs)
        trace_id:    Langfuse trace ID to attach the score to (may be None)
    """
    if not _deepeval_configured:
        return

    factory = _METRIC_FACTORIES.get(metric)
    if factory is None:
        logger.warning("[DEEPEVAL] Unknown metric '%s' — skipping", metric)
        return

    try:
        from deepeval.test_case import LLMTestCase

        eval_metric = factory()
        test_case = LLMTestCase(input=input_text, actual_output=output_text)

        # Run synchronous metric.measure() in a thread to avoid blocking the event loop
        await asyncio.to_thread(eval_metric.measure, test_case)

        score = float(eval_metric.score)
        reason = (getattr(eval_metric, "reason", "") or "")[:500]

        logger.info("[DEEPEVAL] %s → score=%.3f | %s", metric, score, reason[:120] if reason else "")

        if _langfuse_enabled and trace_id:
            from langfuse import get_client
            get_client().create_score(
                trace_id=trace_id,
                name=metric,
                value=score,
                comment=reason or None,
            )
            logger.info(
                "[LANGFUSE] Score '%s'=%.3f attached to trace %s",
                metric, score, trace_id[:8],
            )

    except Exception as exc:
        logger.warning("[DEEPEVAL] Evaluation '%s' failed: %s", metric, exc)
