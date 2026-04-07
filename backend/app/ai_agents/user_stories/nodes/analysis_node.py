import time
import copy
import logging
from typing import Dict, Any
from langsmith import get_current_run_tree, traceable

from app.utils.pipeline_utils import add_trace
from app.ai_agents.user_stories.utils.text_quality_utils import (
    detect_language,
    escape_braces,
)
from app.ai_agents.user_stories.services.ac_extraction_service import ac_extraction_service
from ..services.publishing_service import publishing_service
from ..utils.text_sanitizer import sanitize_story
from ..utils.scoring_utils import compute_all_scores
from ..prompts.analysis import ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


@traceable(name="analysis_node")
async def analysis_node(state: Dict[str, Any]) -> Dict[str, Any]: 
    print(f"[ANALYSIS] BEFORE deepcopy - use_cache: {state.get('use_cache')}")   
    state = copy.deepcopy(state)
    print(f"[ANALYSIS] AFTER deepcopy - use_cache: {state.get('use_cache')}")
    jira_id = state.get("jira_id", "?")
    start_time = time.time()
    print(f"[ANALYSIS_NODE] {jira_id} use_cache: {state.get('use_cache')}")

    state = add_trace(state, "analysis_start", {"jira_id": jira_id})
    run = get_current_run_tree()
    if run:
        run.metadata.update({
            "jira_id": state.get("jira_id"),
            "ac_count": len(state.get("acceptance_criteria", [])),
        })

    # ============================================================
    # 1. STORY INIT
    # ============================================================
    original_story = state.get("raw_story") or ""
    sanitized = sanitize_story(original_story)

    raw_story = sanitized if sanitized.strip() else original_story

    if not raw_story:
        return state

    # ============================================================
    # 2. UI UPDATE
    # ============================================================
    await publishing_service.publish_phase(state, "analyzing")

    # ============================================================
    # 3. AC EXTRACTION (CENTRALISÉE + SAFE)
    # ============================================================
    try:
        existing_ac = state.get("acceptance_criteria")
        # convertir list → string pour le service
        if isinstance(existing_ac, list):
            ac_field = "\n".join(existing_ac)
        else:
            ac_field = existing_ac

        extraction_result = ac_extraction_service.extract(
            description=raw_story,
            acceptance_criteria_field=ac_field,
            jira_id=jira_id
        )

        clean_story = extraction_result.story_clean
        ac = extraction_result.acceptance_criteria
        
        print(f"[{jira_id}] INPUT DESCRIPTION: {clean_story}\n")
        print(f"\n[{jira_id}] INPUT AC COUNT: {len(ac)}")
        print(f"[{jira_id}] INPUT AC: {ac}\n")

    except Exception as e:
        logger.error(f"[{jira_id}] AC extraction failed: {e}")
        clean_story = raw_story
        ac = []

    # IMPORTANT → unifier la variable
    raw_story = clean_story

    state["raw_story"] = clean_story
    state["existing_ac"] = ac
    state["acceptance_criteria"] = ac

    # ============================================================
    # 4. LANGUAGE
    # ============================================================
    language = detect_language(raw_story)
    state["language"] = language

    # ============================================================
    # 5. PROMPT
    # ============================================================
    prompt = ANALYSIS_PROMPT.format(
        story=escape_braces(raw_story),
        language=language,
        context=""
    )

    # ============================================================
    # 6. SCORING
    # ============================================================
    scores = await compute_all_scores(
        story=raw_story,
        ac=ac,
        prompt=prompt,
        task="analysis",
        fallback={
            "llm_score": 0.3,
            "llm_issues": [],
            "llm_suggestions": []
        },
        state=state
    )

    # ============================================================
    # 7. STATE UPDATE
    # ============================================================
    duration = round(time.time() - start_time, 3)

    state.update({
        **scores,

        # scores
        "initial_score": scores["final_score"],

        # best tracking
        "best_score": scores["final_score"],
        "best_story": raw_story,
        "best_ac": ac,

        # refinement init
        "improved_story": None,

        # pipeline
        "iteration": 0,

        # SSE
        "current_step": "analyzing"
    })

    state.setdefault("timing", {})
    state["timing"]["analysis"] = duration

    state = add_trace(state, "analysis_completed", {
        "score": scores["final_score"],
        "ac_count": len(ac),
        "duration": duration
    })

    return state