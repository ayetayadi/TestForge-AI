import html
import re
import time
import copy

from langgraph.graph import END

from app.llm.factory import get_llm
from app.utils.common.pipeline_utils import add_trace, safe_publish
from app.utils.common.llm_safety_utils import is_llm_failed, safe_float, safe_json_parse
from app.utils.common.text_quality_utils import detect_language, escape_braces, is_testable_ac
from app.utils.common.text_quality_utils import is_garbage_story
from app.utils.common.ac_utils import compute_ac_score, normalize_ac
from .tools.rule_engine import rule_engine
from .tools.nlp_checker import nlp_checker
from .prompts import ANALYSIS_PROMPT

# =========================
# CLEAN INPUT
# =========================
def _sanitize_story(raw: str) -> str:
    if isinstance(raw, list):
        raw = " ".join(str(x) for x in raw)

    if not raw:
        return ""
    text = html.unescape(str(raw))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\u00a0\u202f\u2009\u2007\u2002\u2003]", " ", text)
    text = re.sub(r"[^\S\n\t ]+", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# =========================
# MAIN NODE
# =========================
def analysis_node(state: dict) -> dict:
    state = copy.deepcopy(state)
    print("\n[ANALYSIS INPUT]", state)
    is_reanalysis = state.get("is_reanalysis", False)
    label = "RE-ANALYSIS" if is_reanalysis else "ANALYSIS"
    jira_id = state.get("jira_id", "?")
    print(f"[{jira_id}] [DEBUG] analysis_node started")

    print(f"[{jira_id}] >>> [{label} START]")
    start_time = time.time()

    # =========================
    # SOURCE STORY
    # =========================
    if is_reanalysis:
        source_story = state.get("improved_story") or state.get("raw_story") or ""
    else:
        source_story = state.get("raw_story") or ""

    story = _sanitize_story(source_story)

    print(f"[{jira_id}] >>> {label} STORY: {story}")
    print(f"[{jira_id}] >>> SOURCE: {'improved_story' if is_reanalysis else 'raw_story'}")

    # Fix initial story
    state["initial_story"] = state.get("initial_story") or story

    if not story:
        return {**state, **_empty_analysis_result(state)}

    safe_publish(state, "analysis_started", {
        "story_id": jira_id,
        "iteration": state.get("iteration", 0),
        "reanalysis": state.get("is_reanalysis", False)
    })

    # =========================
    # NORMALIZE EXISTING ACs EARLY
    # =========================
    raw_existing_ac = state.get("existing_ac") or []
    normalized_existing_ac = normalize_ac(raw_existing_ac)

    if len(normalized_existing_ac) != len(raw_existing_ac):
        print(f"[{jira_id}] [AC NORMALIZE] {len(raw_existing_ac)} raw → {len(normalized_existing_ac)} normalized")
        for i, ac in enumerate(normalized_existing_ac):
            print(f"[{jira_id}] [AC NORMALIZE]   {i+1}. {ac}")

    # Update state with normalized ACs so downstream nodes get clean data
    state["existing_ac"] = normalized_existing_ac

    # =========================
    # RULE ENGINE
    # =========================
    try:
        rule_result = rule_engine.evaluate(story)
    except Exception:
        rule_result = {
            "rule_score": 0.0,
            "rule_issues": [],
            "rule_suggestions": []
        }

    # =========================
    # NLP CHECK
    # =========================
    try:
        nlp_result = nlp_checker.analyze(story)
    except Exception:
        nlp_result = {
            "nlp_score": 0.0,
            "nlp_issues": [],
            "nlp_suggestions": []
        }

    rule_score = safe_float(rule_result.get("rule_score", 0))
    nlp_score  = safe_float(nlp_result.get("nlp_score", 0))

    # =========================
    # LLM ANALYSIS
    # =========================
    previous_llm_score = safe_float(state.get("llm_score", 0.3))
    fallback_llm_score = previous_llm_score if is_reanalysis else 0.3

    llm_failed = True
    llm_score  = fallback_llm_score
    llm_issues = []
    llm_suggestions = []

    try:
        llm = get_llm("analysis")
        print(f"[{jira_id}] [DEBUG] LLM instance created")
        prompt = ANALYSIS_PROMPT.format(
            story=escape_braces(story),
            language=detect_language(story),
            context=""
        )
        print(f"[{jira_id}] [DEBUG] Prompt formatted, length={len(prompt)}")
        response = llm.generate(prompt, temperature=0.0)
        print(f"[{jira_id}] [DEBUG] LLM response type={type(response)}")
        print(f"[{jira_id}] [DEBUG] LLM response={response}")

        # FIX: Check both the string pattern AND the dict key.
        # When the LLM HTTP call fails (429, timeout), the factory returns
        # a fallback dict like {'llm_failed': True, 'llm_score': 0.3}.
        # is_llm_failed(str(response)) doesn't catch this because it
        # looks for text patterns, not dict keys. So we also check the
        # response dict directly.
        if isinstance(response, dict) and response.get("llm_failed") is True:
            llm_failed = True
            print(f"[{jira_id}] [DEBUG] llm_failed=True (from response dict)")
        else:
            llm_failed = is_llm_failed(str(response))
            print(f"[{jira_id}] [DEBUG] llm_failed={llm_failed}")
        if not llm_failed:
            parsed = response

            # Drift detection
            if any(k in parsed for k in ["improved_story", "acceptance_criteria"]):
                print(f"[{jira_id}] [ERROR] LLM DRIFT DETECTED → fallback")
                llm_failed = True
                llm_score  = fallback_llm_score
            else:
                llm_score = safe_float(parsed.get("llm_score", fallback_llm_score))
                llm_issues = parsed.get("llm_issues", [])
                llm_suggestions = parsed.get("llm_suggestions", [])

    except Exception as e:
        print(f"[{jira_id}] [LLM ERROR] {e}")

    if llm_failed:
        print(f"[{jira_id}] [LLM FAILED] using fallback score={fallback_llm_score}")

    # =========================
    # AC SCORING
    # =========================
    # Use acceptance_criteria (from refinement) if available, else normalized existing_ac
    ac = state.get("acceptance_criteria") or normalized_existing_ac
    ac = normalize_ac(ac)
    ac_score = compute_ac_score(ac, is_testable_ac)

    print(f"[{jira_id}] [AC SCORE] {len(ac)} ACs → score={ac_score}")

    if ac:
        final_score = (
            llm_score  * 0.20 +
            ac_score   * 0.40 +
            rule_score * 0.25 +
            nlp_score  * 0.15
        )
    else:
        final_score = (
            llm_score  * 0.30 +
            rule_score * 0.40 +
            nlp_score  * 0.30
        )

    # =========================
    # GARBAGE DETECTION
    # =========================
    if is_garbage_story(story):
        print(f"[{jira_id}] [QUALITY] Garbage story detected")
        final_score = min(final_score, 0.3)

    # =========================
    # NORMALIZE
    # =========================
    final_score = round(max(0.0, min(1.0, final_score)), 2)

    print(f"[{jira_id}] [DEBUG SCORE] rule={rule_score} nlp={nlp_score} llm={llm_score} ac={ac_score} → final={final_score}")

    # =========================
    # INITIAL SCORE
    # =========================
    if state.get("initial_score") is None:
        state["initial_score"] = final_score

    # =========================
    # TRACE
    # =========================
    state = add_trace(state, label.lower(), {
        "rule": rule_score,
        "nlp": nlp_score,
        "llm": llm_score,
        "ac": ac_score,
        "final": final_score,
        "llm_failed": llm_failed,
    })

    duration = round(time.time() - start_time, 3)

    # =========================
    # STATE UPDATE
    # =========================
    state.update({
        "rule_score": rule_score,
        "rule_issues": rule_result.get("rule_issues", []),
        "rule_suggestions": rule_result.get("rule_suggestions", []),

        "nlp_score": nlp_score,
        "nlp_issues": nlp_result.get("nlp_issues", []),
        "nlp_suggestions": nlp_result.get("nlp_suggestions", []),

        "llm_score": llm_score,
        "llm_issues": llm_issues,
        "llm_suggestions": llm_suggestions,
        "llm_failed": llm_failed,

        "final_score": final_score,
        "best_score": max(state.get("best_score", 0), final_score),

        "timing": {
            **state.get("timing", {}),
            label.lower(): duration,
        },
    })

    safe_publish(state, "analysis_completed", {
        "jira_id": jira_id,
        "score": final_score,
        "duration": duration,
        "llm_failed": llm_failed,
        "reanalysis": state.get("is_reanalysis", False),
        "iteration": state.get("iteration", 0),
    })

    print(f"[{jira_id}] [{label} DONE] score={final_score} time={duration}s")
    print(f"[{jira_id}] [DEBUG AC] existing_ac={state.get('existing_ac')} | acceptance_criteria={state.get('acceptance_criteria')}")
    return state


# =========================
# EMPTY FALLBACK
# =========================
def _empty_analysis_result(state: dict) -> dict:
    return {
        "rule_score": 0.0,
        "rule_issues": ["User story is empty or missing"],
        "rule_suggestions": ["Provide a valid user story"],

        "nlp_score": 0.0,
        "nlp_issues": [],
        "nlp_suggestions": [],

        "llm_score": 0.3,
        "llm_issues": [],
        "llm_suggestions": [],
        "llm_failed": True,

        "final_score": 0.0,
        "initial_score": state.get("initial_score", 0.0),
        "best_score": state.get("best_score", 0.0),

        "acceptance_criteria": state.get("acceptance_criteria", []),
        "existing_ac": state.get("existing_ac"),

        "is_reanalysis": state.get("is_reanalysis", False),
    }