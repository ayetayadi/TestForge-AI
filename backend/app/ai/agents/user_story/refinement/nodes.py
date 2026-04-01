import asyncio
import html
import re
import time
from app.utils.common.embedding import embed, cosine_similarity
from app.llm.factory import get_llm
from app.utils.common.pipeline_utils import safe_publish, add_trace
from app.utils.common.llm_safety_utils import is_llm_failed
from app.utils.common.text_quality_utils import (
    detect_language, clean_story_output, escape_braces, is_testable_ac,
    deduplicate_ac, normalize_list
)
from app.utils.common.ac_utils import normalize_ac
from .tools.template_engine import template_engine
from .tools.ac_generator import ac_generator
from .tools.constraint_guard import constraint_guard
from .prompts import REFINEMENT_PROMPT, AC_REPAIR_PROMPT
from app.core.config import settings
import copy

# =========================
# HELPERS
# =========================

def _sanitize_story(raw: str) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\u00a0\u202f\u2009\u2007\u2002\u2003]", " ", text)
    text = re.sub(r"[^\S\n\t ]+", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_actor(story: str) -> str:
    match = re.search(r"en tant qu[e']?\s+([^,\n]+)", story.lower())
    return match.group(1).strip() if match else ""


def _is_incomplete_sentence(ac: str) -> bool:
    ac_stripped = ac.strip()
    if not ac_stripped:
        return True

    trailing_words = [
        "to", "the", "a", "an", "of", "in", "for", "and", "or", "with",
        "de", "du", "des", "le", "la", "les", "un", "une", "et",
        "ou", "à", "au", "aux", "en", "par", "sur", "vers"
    ]
    last_word = ac_stripped.rstrip(".!?,;:").split()[-1].lower() if ac_stripped.split() else ""
    if last_word in trailing_words:
        return True

    words = ac_stripped.split()
    if words:
        first_word = words[0]
        if (len(first_word) <= 3 and first_word.isupper() and len(words) > 1
                and not first_word.lower() in ["le", "la", "si", "if", "un"]):
            return True

    return False


def _filter_drifted_ac(ac_list: list, story: str, jira_id: str = "?") -> list:
    """
    Detect and remove AC that describe the OPPOSITE action of the story.

    Root cause: LLMs pattern-match "déconnexion" → auth domain → generate
    login AC. This explicitly catches opposite-action drift.
    """
    story_lower = story.lower()

    # Map: if story contains key → AC must NOT contain any of the values
    opposite_actions = {
        # French logout
        "déconnexion": ["connexion avec", "se connecter", "identifiants", "mot de passe",
                        "saisit un email", "email et un mot", "tentative de connexion"],
        "déconnecter": ["connexion avec", "se connecter", "identifiants", "mot de passe",
                        "saisit un email", "email et un mot", "tentative de connexion"],
        # French export/import
        "export": ["import", "importer", "importation"],
        "import": ["export", "exporter", "exportation"],
        # French delete/create
        "suppression": ["création", "créer", "ajouter"],
        "supprimer": ["création", "créer", "ajouter"],
        "création": ["suppression", "supprimer", "effacer"],
        "créer": ["suppression", "supprimer", "effacer"],
        # English logout
        "logout": ["login", "log in", "sign in", "credentials", "password", "email and password"],
        "log out": ["login", "log in", "sign in", "credentials", "password"],
        "sign out": ["sign in", "log in", "login", "credentials"],
        # English delete/create
        "delete": ["create", "creation", "add"],
        "create": ["delete", "deletion", "remove"],
    }

    story_action = None
    blocked_terms = []
    for action, opposites in opposite_actions.items():
        if action in story_lower:
            story_action = action
            blocked_terms.extend(opposites)

    if not blocked_terms:
        return ac_list

    filtered = []
    for ac in ac_list:
        ac_lower = ac.lower()
        is_drifted = False
        for term in blocked_terms:
            if term in ac_lower:
                print(f"[{jira_id}] [AC DRIFT] Story is about '{story_action}', "
                      f"but AC contains '{term}': {ac[:80]}...")
                is_drifted = True
                break
        if not is_drifted:
            filtered.append(ac)

    if len(filtered) < len(ac_list):
        print(f"[{jira_id}] [AC DRIFT] Removed {len(ac_list) - len(filtered)} "
              f"drifted ACs out of {len(ac_list)}")

    return filtered


async def repair_ac_with_llm(story: str, ac_list: list, jira_id: str = "?") -> list:
    if not ac_list:
        return []
    try:
        llm = get_llm("ac_repair")
        language = detect_language(story)
        prompt = AC_REPAIR_PROMPT.format(
            story=story,
            ac=str(ac_list),
            language=language
        )
         
        response = await asyncio.to_thread(
            llm.generate,
            prompt,
            temperature=settings.AC_REPAIR_TEMP,
        )
        repaired = response.get("acceptance_criteria") or []
        repaired = normalize_ac(repaired)
        if not repaired:
            return ac_list
        return [str(a) for a in repaired if a]
    except Exception as e:
        print(f"[{jira_id}] [AC REPAIR ERROR] {e}")
        return ac_list


def _finalize_ac(ac: list) -> list:
    ac = [a for a in ac if not _is_incomplete_sentence(a)]

    testable = [a for a in ac if is_testable_ac(a)]

    if len(testable) >= 2:
        base = testable
    else:
        print("[WARN] Keeping original AC (not enough testable)")
        base = ac

    deduped = deduplicate_ac(base)
    return list(dict.fromkeys(deduped))[:5]


def normalize_text(s) -> str:
    if isinstance(s, list):
        s = " ".join(str(x) for x in s)
    if not isinstance(s, str):
        s = str(s or "")
    return re.sub(r"\s+", " ", s.strip().lower())


def _format_existing_ac(existing_ac: list) -> str:
    """Format existing AC list into a readable string for the prompt."""
    if not existing_ac:
        return "None provided"
    return "\n".join(f"- {ac}" for ac in existing_ac)


# =========================
# MAIN NODE
# =========================
async def refinement_node(state: dict) -> dict:
    state = state.copy()
    jira_id = state.get("jira_id", "?")
    print(f"\n[{jira_id}] >>> [REFINEMENT START]")
    start_time = time.time()

    safe_publish(state, "refinement_started", {
        "story_id": jira_id,
        "iteration": state.get("iteration", 0)
    })

    raw_story = state.get("raw_story", "")
    original_story = state.get("improved_story") or _sanitize_story(raw_story)
    language = detect_language(original_story)
    existing_ac = normalize_ac(state.get("existing_ac") or [])

    state["iteration"] = state.get("iteration", 0) + 1

    # =========================
    # EARLY EXIT
    # =========================
    existing_ac_valid = [a for a in existing_ac if is_testable_ac(a)]
    if existing_ac and len(existing_ac_valid) >= len(existing_ac) * 0.6 and state.get("final_score", 0) > 0.95:
        print(f"[{jira_id}] [REFINEMENT] Skipped — high quality")
        return {
            **state,
            "improved_story": state.get("improved_story", original_story),
            "acceptance_criteria": state.get("acceptance_criteria", existing_ac),
            "skip_reanalysis": True,
        }

    # =========================
    # PREPARE INPUT
    # =========================
    issues = normalize_list(
        (state.get("rule_issues") or []) +
        (state.get("nlp_issues") or []) +
        (state.get("llm_issues") or [])
    )
    suggestions = normalize_list(
        (state.get("rule_suggestions") or []) +
        (state.get("nlp_suggestions") or []) +
        (state.get("llm_suggestions") or [])
    )

    normalized_story = template_engine.normalize(original_story)

    # =========================
    # LLM CALL
    # =========================
    llm_failed = False
    candidate_story = original_story
    raw_llm_ac = []

    try:
        if state.get("refine_ac_only"):
            print(f"[{jira_id}] [AC ONLY MODE] Skipping story refinement LLM")
            repaired = await repair_ac_with_llm(original_story, existing_ac, jira_id)
            raw_llm_ac = normalize_ac(repaired)
            candidate_story = original_story
        else:
            llm = get_llm("refinement")

            # ─── FIX: Format existing AC for prompt injection ───
            ac_text = _format_existing_ac(existing_ac)

            base_prompt = REFINEMENT_PROMPT.format(
                story=escape_braces(normalized_story),
                existing_ac=escape_braces(ac_text),
                issues="\n".join(issues) if issues else "None",
                suggestions="\n".join(suggestions) if suggestions else "None",
                language=language,
            )

            # Language enforcement suffix
            lang_labels = {"fr": "French (français)", "en": "English"}
            lang_label = lang_labels.get(language, language)
            language_suffix = (
                f"\n\nCRITICAL: The story is in {lang_label}. "
                f"ALL acceptance_criteria MUST be written in {lang_label}. "
                f"Do NOT write acceptance criteria in any other language."
            )

            response = await asyncio.to_thread(
                llm.generate,
                base_prompt + language_suffix,
                temperature=settings.REFINEMENT_TEMP,
            )

            # Check for LLM failure
            if isinstance(response, dict) and response.get("llm_failed") is True:
                llm_failed = True
            else:
                llm_failed = is_llm_failed(str(response))

            if not llm_failed:
                candidate_story = response.get("improved_story") or normalized_story
                if isinstance(candidate_story, list):
                    candidate_story = " ".join(str(x) for x in candidate_story)
                candidate_story = clean_story_output(candidate_story)
                raw_llm_ac = normalize_ac(response.get("acceptance_criteria") or [])

    except Exception as e:
        print(f"[{jira_id}] [ERROR] LLM call failed: {e}")
        llm_failed = True

    if llm_failed:
        return {
            **state,
            "improved_story": original_story,
            "acceptance_criteria": existing_ac,
            "skip_reanalysis": True,
            "llm_failed": True,
        }

    # =========================
    # LANGUAGE ENFORCEMENT
    # =========================
    if raw_llm_ac and language:
        lang_matched = []
        for ac_item in raw_llm_ac:
            ac_lang = detect_language(ac_item)
            if ac_lang == language:
                lang_matched.append(ac_item)
            else:
                print(f"[{jira_id}] [LANG REJECT] AC in '{ac_lang}', expected '{language}': {ac_item[:60]}...")
        if len(lang_matched) < len(raw_llm_ac):
            print(f"[{jira_id}] [LANG FILTER] {len(raw_llm_ac) - len(lang_matched)} ACs rejected for language mismatch")
        raw_llm_ac = lang_matched

    # =========================
    # INCOMPLETE AC FILTER
    # =========================
    if raw_llm_ac:
        complete_ac = [a for a in raw_llm_ac if not _is_incomplete_sentence(a)]
        if len(complete_ac) < len(raw_llm_ac):
            print(f"[{jira_id}] [TRUNCATION FILTER] {len(raw_llm_ac) - len(complete_ac)} incomplete ACs removed")
        raw_llm_ac = complete_ac

    # =========================
    # SEMANTIC AC DRIFT CHECK
    # =========================
    if raw_llm_ac and original_story:
        raw_llm_ac = _filter_drifted_ac(raw_llm_ac, original_story, jira_id)

    # =========================
    # SEMANTIC + DOMAIN GUARD
    # =========================
    if not state.get("refine_ac_only"):
        try:
            if not original_story or not candidate_story:
                sim = 0.0
            else:
                emb_a = await asyncio.to_thread(embed, original_story)
                emb_b = await asyncio.to_thread(embed, candidate_story)
                sim = cosine_similarity(emb_a, emb_b)
        except Exception as e:
            print(f"[{jira_id}] [SIM ERROR] {e}")
            sim = 0.0

        print(f"[{jira_id}] [SIM] {sim:.3f}")

        guard_result = constraint_guard.validate(
            original_story,
            candidate_story,
            raw_llm_ac
        )

        if guard_result.get("critical_issues"):
            print(f"[{jira_id}] [GUARD FAIL] {guard_result['critical_issues']}")
            return {
                **state,
                "improved_story": original_story,
                "acceptance_criteria": existing_ac,
                "skip_reanalysis": True,
            }

        if sim < 0.85:
            print(f"[{jira_id}] [REJECT] drift (low similarity)")
            return {
                **state,
                "improved_story": original_story,
                "acceptance_criteria": existing_ac,
                "skip_reanalysis": True,
            }

        print(f"[{jira_id}] [GUARD OK] {guard_result.get('guard_issues', [])}")
        improved_story = candidate_story
    else:
        print(f"[{jira_id}] [AC ONLY] Keeping original story")
        improved_story = original_story

    # =========================
    # AC PIPELINE
    # =========================
    if state.get("refine_ac_only"):
        valid_llm_ac = [a for a in raw_llm_ac if is_testable_ac(a)]
        if valid_llm_ac:
            print(f"[{jira_id}] [AC ONLY] {len(valid_llm_ac)} repaired AC valid")
    else:
        valid_provenance_ac, rejected_ac = constraint_guard.validate_ac_provenance(
            raw_llm_ac,
            original_story,
            language
        )

        if rejected_ac:
            for r in rejected_ac:
                print(f"[{jira_id}] [AC REJECTED] {r['reason']}: {r['ac'][:60]}...")

        valid_llm_ac = [a for a in valid_provenance_ac if is_testable_ac(a)]

        if len(valid_llm_ac) < 2:
            print(f"[{jira_id}] [AC FALLBACK] Only {len(valid_llm_ac)} valid → template generator")
            valid_llm_ac = []

    # =========================
    # SELECT SOURCE
    # =========================
    MIN_VALID_AC = 2

    if valid_llm_ac:
        print(f"[{jira_id}] [AC MERGE] merging LLM + existing")

        quality_existing = [
            a for a in existing_ac
            if is_testable_ac(a) and len(a.split()) >= 4
        ]

        quality_llm = [
            a for a in valid_llm_ac
            if is_testable_ac(a) and len(a.split()) >= 5
        ]

        merged = quality_existing.copy()
        for ac_item in quality_llm:
            if ac_item not in merged:
                merged.append(ac_item)

        if len(merged) < MIN_VALID_AC:
            print(f"[{jira_id}] [FALLBACK] Not enough merged AC → using existing")
            ac = existing_ac
        else:
            ac = merged[:5]

    elif existing_ac:
        quality_existing = [
            a for a in existing_ac
            if is_testable_ac(a) and len(a.split()) >= 6
        ]

        if len(quality_existing) >= MIN_VALID_AC:
            print(f"[{jira_id}] [AC SOURCE] Using EXISTING AC ({len(quality_existing)})")
            ac = quality_existing
        else:
            print(f"[{jira_id}] [AC GENERATE] Existing AC not testable-grade → trying generator")
            generated = await asyncio.to_thread(ac_generator.generate, original_story, [])
            generated = normalize_ac(generated or [])
            generated = [a for a in generated if is_testable_ac(a)]

            if len(generated) >= MIN_VALID_AC:
                ac = generated
            else:
                print(f"[{jira_id}] [AC KEEP EXISTING] Generator failed → preserving {len(existing_ac)} original ACs")
                ac = existing_ac
    else:
        print(f"[{jira_id}] [AC GENERATE] No AC → generating")
        ac = await asyncio.to_thread(ac_generator.generate, original_story, [])

    # =========================
    # FINAL GUARD
    # =========================
    ac = normalize_ac(ac)

    # ─── FIX: Apply drift filter to final AC too ───
    if ac and original_story:
        ac = _filter_drifted_ac(ac, original_story, jira_id)

    testable_ac = [a for a in ac if is_testable_ac(a)]

    if len(testable_ac) >= MIN_VALID_AC:
        ac = testable_ac
    else:
        print(f"[{jira_id}] [FINAL GUARD] Only {len(testable_ac)} testable ACs — keeping all {len(ac)} ACs")

    if len(ac) == 0:
        print(f"[{jira_id}] [FORCE GENERATE] AC empty → regenerate")
        ac = await asyncio.to_thread(ac_generator.generate, original_story, [])
        ac = normalize_ac(ac or [])
        testable_ac = [a for a in ac if is_testable_ac(a)]
        ac = testable_ac if testable_ac else ac

    # If still empty, use raw LLM AC as last resort (but filter drift)
    if len(ac) == 0 and raw_llm_ac:
        print(f"[{jira_id}] [LAST RESORT] Using raw LLM AC")
        ac = [a for a in raw_llm_ac if is_testable_ac(a)]
        ac = _filter_drifted_ac(ac, original_story, jira_id)

    # If STILL empty and we had existing ACs, always preserve them
    if len(ac) == 0 and existing_ac:
        print(f"[{jira_id}] [PRESERVE] Returning original existing ACs")
        ac = existing_ac

    # =========================
    # FINALIZE
    # =========================
    ac = _finalize_ac(ac) if any(is_testable_ac(a) for a in ac) else list(dict.fromkeys(ac))[:5]

    state["llm_raw_ac"] = raw_llm_ac
    state["validated_ac"] = valid_llm_ac
    state["final_ac"] = ac

    # =========================
    # IMPROVEMENT CHECK
    # =========================
    story_changed = normalize_text(improved_story) != normalize_text(original_story)

    old_ac = normalize_ac(state.get("acceptance_criteria") or [])
    ac_changed = set(ac) != set(old_ac)

    has_improvement = story_changed or ac_changed

    if not has_improvement:
        print(f"[{jira_id}] [REVERT] no improvement")
        return {
            **state,
            "improved_story": original_story,
            "acceptance_criteria": existing_ac,
            "skip_reanalysis": True,
        }

    state["refine_ac_only"] = False

    # =========================
    # FINAL STATE
    # =========================
    duration = round(time.time() - start_time, 3)

    job_id = state.get("job_id")
    if job_id:
        from app.streaming.sse_manager import publish_event
        publish_event(job_id, "improvement_complete", {
            "type": "improvement_complete",
            "issue_key": jira_id,
            "iteration": state.get("iteration", 0),
        })

    print(f"[{jira_id}] [FINAL] improved={improved_story}")
    print(f"[{jira_id}] [FINAL] ac={ac}")

    safe_publish(state, "refinement_completed", {
        "story_id": jira_id,
        "improved": story_changed,
        "ac_count": len(ac),
        "iteration": state.get("iteration", 0),
    })

    state.update({
        "improved_story": improved_story,
        "acceptance_criteria": ac,
        "skip_reanalysis": False,
        "llm_failed": False,
        "timing": {
            **state.get("timing", {}),
            "refinement": duration,
        },
    })

    return state