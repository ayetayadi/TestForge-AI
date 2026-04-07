import time
import copy
import asyncio
import logging
from typing import Dict, Any, Tuple
from langsmith import get_current_run_tree, traceable

from app.utils.pipeline_utils import add_trace
from app.ai_agents.user_stories.utils.text_quality_utils import (
    detect_language,
    clean_story_output,
    escape_braces,
    normalize_list,
)
from app.core.embedding import embed, cosine_similarity
from app.llm.service import llm_service

from ..services.ac_service import ac_service
from ..services.publishing_service import publishing_service
from ..tools.template_engine import template_engine
from ..tools.constraint_guard import constraint_guard
from ..utils.text_sanitizer import sanitize_story
from ..utils.filters import LanguageFilter, CompletenessFilter, DriftFilter
from ..prompts.refinement import REFINEMENT_PROMPT

logger = logging.getLogger(__name__)

BASE_SIMILARITY_THRESHOLD = 0.68
MIN_SIMILARITY_THRESHOLD = 0.55

MAX_ISSUES = 10
MAX_SUGGESTIONS = 6
MAX_AC = 5

DEBUG_LLM = True

# ============================================================
# DYNAMIC THRESHOLD
# ============================================================
def _compute_dynamic_threshold(iteration: int, ac_quality_score: float = 1.0) -> float:
    base = BASE_SIMILARITY_THRESHOLD

    if ac_quality_score < 0.3:
        base -= 0.08

    decay = 0.03 * (iteration - 1)
    return max(base - decay, MIN_SIMILARITY_THRESHOLD)


# ============================================================
# MAIN NODE
# ============================================================
@traceable(name="refinement_node")
async def refinement_node(state: Dict[str, Any]) -> Dict[str, Any]:

    state = copy.deepcopy(state)
    jira_id = state.get("jira_id", "?")
    start_time = time.time()
    print(f"[REFINEMENT_NODE] {jira_id} use_cache: {state.get('use_cache')}")

    # ============================================================
    # ITERATION
    # ============================================================
    iteration = state.get("iteration", 0) + 1
    state["iteration"] = iteration

    run = get_current_run_tree()
    if run:
        run.metadata.update({
            "jira_id": jira_id,
            "iteration": iteration,
            "task": "refinement",
        })

    state = add_trace(state, "refinement_start", {
        "iteration": iteration,
        "jira_id": jira_id
    })

    # ============================================================
    # UI (SSE CLEAN)
    # ============================================================
    await publishing_service.publish_phase(state, "refining")

    # ============================================================
    # INPUT
    # ============================================================
    original_story = (
        state.get("improved_story")
        or sanitize_story(state.get("raw_story", ""))
    )

    if not original_story:
        return _finalize_state(state, original_story, [], start_time, failed=True)

    language = state.get("language") or detect_language(original_story)
    existing_ac = state.get("existing_ac") or []
    current_ac = state.get("acceptance_criteria") or existing_ac

    # ============================================================
    # PROMPT
    # ============================================================
    issues = _collect_issues(state)
    suggestions = _collect_suggestions(state)

    prompt = REFINEMENT_PROMPT.format(
        story=escape_braces(template_engine.normalize(original_story)),
        existing_ac=_format_ac_list(current_ac),
        issues=_format_list(issues) or "None",
        suggestions=_format_list(suggestions) or "None",
        language=language,
    )

    if DEBUG_LLM:
        print(f"\n[{jira_id}] ===== LLM INPUT (REFINEMENT) =====")
        print(f"[{jira_id}] ITERATION: {iteration}")
        print(f"[{jira_id}] STORY:\n{original_story}")
        print(f"[{jira_id}] EXISTING AC ({len(current_ac)}):")
        for i, a in enumerate(current_ac, 1):
            print(f"  {i}. {a}")
        print(f"[{jira_id}] ISSUES: {issues}")
        print(f"[{jira_id}] SUGGESTIONS: {suggestions}")
        print(f"[{jira_id}] PROMPT:\n{prompt[:500]}")
        print(f"[{jira_id}] ==================================\n")

    # ============================================================
    # LLM CALL
    # ============================================================
    response = await llm_service.call_with_fallback(
        prompt=prompt,
        task="refinement",
        fallback={
            "improved_story": original_story,
            "acceptance_criteria": current_ac
        },
        use_cache=state.get("use_cache", True)
    )

    if DEBUG_LLM:
       print(f"\n[{jira_id}] ===== LLM RAW OUTPUT =====")
       print(f"[{jira_id}] RESPONSE TYPE: {type(response)}")
       print(f"[{jira_id}] RESPONSE:\n{response}")
       print(f"[{jira_id}] ============================\n")

    if not isinstance(response, dict):
        return _finalize_state(state, original_story, current_ac, start_time, llm_failed=True)

    candidate_story = clean_story_output(
        response.get("improved_story") or original_story
    )
    raw_ac = response.get("acceptance_criteria") or []

    if DEBUG_LLM:
        print(f"\n[{jira_id}] ===== LLM PARSED OUTPUT =====")
        print(f"[{jira_id}] CANDIDATE STORY:\n{candidate_story}")
        print(f"[{jira_id}] RAW AC ({len(raw_ac)}):")
        for i, a in enumerate(raw_ac, 1):
            print(f"  {i}. {a}")
        print(f"[{jira_id}] ==============================\n")

    # ============================================================
    # SIMILARITY CHECK (SAFE)
    # ============================================================
    is_valid, similarity = await _check_similarity(
        original_story,
        candidate_story,
        iteration,
        state.get("ac_score", 1.0)
    )

    if not is_valid:
        state["refinement_status"] = "rejected"

        best_story = state.get("best_story", original_story)
        best_ac = state.get("best_ac", current_ac)

        state["refinement_status"] = "rejected"

        return _finalize_state(state, best_story, best_ac, start_time)

    # ============================================================
    # AC PROCESSING
    # ============================================================
    processed_ac = await _process_ac(
        raw_ac, existing_ac, candidate_story, language
    )

    if DEBUG_LLM:
         print(f"\n[{jira_id}] ===== AC AFTER PROCESSING =====")
         print(f"[{jira_id}] FINAL AC ({len(processed_ac)}):")
         for i, a in enumerate(processed_ac, 1):
             print(f"  {i}. {a}")
         print(f"[{jira_id}] =================================\n")

    # ============================================================
    # NO CHANGE
    # ============================================================
    if not _has_meaningful_change(candidate_story, original_story, processed_ac, current_ac):
        return _finalize_state(state, original_story, current_ac, start_time)

    # ============================================================
    # SUCCESS
    # ============================================================
    state.update({
        "improved_story": candidate_story,
        "acceptance_criteria": processed_ac,
        "llm_failed": False,
        "refinement_status": "ok"
    })

    if DEBUG_LLM:
        print(f"\n[{jira_id}] ===== REFINEMENT DECISION =====")
        print(f"[{jira_id}] STORY CHANGED: {candidate_story != original_story}")
        print(f"[{jira_id}] AC CHANGED: {processed_ac != current_ac}")
        print(f"[{jira_id}] STATUS: {state.get('refinement_status')}")
        print(f"[{jira_id}] =================================\n")

    return state


# ============================================================
# HELPERS
# ============================================================

async def _check_similarity(original, candidate, iteration, ac_quality):
    try:
        emb1, emb2 = await asyncio.gather(
            asyncio.to_thread(embed, original),
            asyncio.to_thread(embed, candidate)
        )

        sim = cosine_similarity(emb1, emb2)
        threshold = _compute_dynamic_threshold(iteration, ac_quality)

        return sim >= threshold, sim

    except Exception as e:
        logger.error(f"Error occurred while checking similarity: {e}")
        return True, 0.5


async def _process_ac(raw_ac, existing_ac, story, language):
    if raw_ac:
        ac = raw_ac
    else:
        return existing_ac[:MAX_AC]

    if not ac:
        return existing_ac[:MAX_AC]

    try:
        print(f"[AC DEBUG] Input: {len(ac)} ACs")
        
        ac = ac_service.normalize(ac)
        print(f"[AC DEBUG] After normalize: {len(ac)} ACs")
        
        ac = LanguageFilter.filter_by_language(ac, language, "")
        print(f"[AC DEBUG] After LanguageFilter: {len(ac)} ACs")
        
        ac = CompletenessFilter.filter_complete(ac, "")
        print(f"[AC DEBUG] After CompletenessFilter: {len(ac)} ACs")
        
        ac = DriftFilter.filter_drifted_ac(ac, story, "")
        print(f"[AC DEBUG] After DriftFilter: {len(ac)} ACs")

        filtered = ac_service.filter_testable(ac)
        print(f"[AC DEBUG] After filter_testable: {len(filtered)} ACs")
        
        if len(filtered) >= 2:
            ac = filtered

        valid_ac, _ = constraint_guard.validate_ac_provenance(ac, story, language)
        print(f"[AC DEBUG] After validate_ac_provenance: {len(valid_ac) if valid_ac else 0} ACs")

        return valid_ac[:MAX_AC] if valid_ac else existing_ac[:MAX_AC]

    except Exception as e:
        print(f"[AC DEBUG] Exception: {e}")
        return existing_ac[:MAX_AC]
    

def _has_meaningful_change(new_story, old_story, new_ac, old_ac):
    story_changed = new_story.strip() != old_story.strip()
    ac_changed = new_ac != old_ac
    return story_changed or ac_changed


def _collect_issues(state):
    return normalize_list(
        (state.get("rule_issues") or []) +
        (state.get("nlp_issues") or []) +
        (state.get("llm_issues") or [])
    )[:MAX_ISSUES]


def _collect_suggestions(state):
    return normalize_list(
        (state.get("rule_suggestions") or []) +
        (state.get("nlp_suggestions") or []) +
        (state.get("llm_suggestions") or [])
    )[:MAX_SUGGESTIONS]


def _format_list(items):
    return "\n".join(f"- {i}" for i in items) if items else ""


def _format_ac_list(ac):
    return "\n".join(f"- {a}" for a in ac) if ac else "None"


def _finalize_state(state, story, ac, start_time, llm_failed=False, failed=False):
    duration = round(time.time() - start_time, 3)

    state.update({
        "improved_story": story,
        "acceptance_criteria": ac,
        "llm_failed": llm_failed
    })

    state.setdefault("timing", {})
    state["timing"][f"refinement_iter_{state.get('iteration', 1)}"] = duration

    return state