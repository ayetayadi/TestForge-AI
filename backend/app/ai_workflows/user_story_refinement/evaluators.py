"""
Quality evaluators for user story refinement pipeline.

Three plain async functions — no LLM, no agent, no framework wrappers:
  - extract_acceptance_criteria  → parse and clean AC from story text
  - score_story                  → multi-criterion quality scoring
  - validate_constraints         → safety / constraint guard
"""

import re
import asyncio
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ============================================================
# PRIVATE HELPERS
# ============================================================

def _detect_language(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["en tant que", "je veux", "afin de", "pour que"]):
        return "fr"
    if any(w in t for w in ["as a", "i want", "so that"]):
        return "en"
    return "fr" if sum(1 for c in text if c in "àâçéèêëîïôûùüÿœæ") >= 2 else "en"


def _extract_role(text: str) -> str:
    m = re.search(
        r"(?:as an?|en tant qu[e']?)\s+([^,\n]+?)(?:,|\s+(?:i want|je veux)|$)",
        text.lower(),
    )
    return m.group(1).strip() if m else ""


def _is_garbage(story: str) -> bool:
    if not story or len(story.strip()) < 10 or len(story) > 5000:
        return True
    s = story.lower().strip()
    patterns = [r"^[0-9\s]+$", r"^[a-zA-Z\s]{0,5}$", r"lorem ipsum", r"test test test", r"^[^a-zA-Z]+$"]
    return any(re.search(p, s) for p in patterns)


def _rule_score(story: str) -> Dict[str, Any]:
    issues: List[str] = []
    suggestions: List[str] = []
    score = 1.0
    sl = story.lower()

    has_role = bool(re.search(r"\bas an?\b", sl) or re.search(r"\ben tant qu[e']?\b", sl))
    has_action = bool(re.search(r"\bi want\b", sl) or re.search(r"\bje veux\b", sl) or re.search(r"\bje souhaite\b", sl))
    if not (has_role and has_action):
        issues.append("Missing user story format (As a… I want…)")
        suggestions.append("Use: As a [role], I want [feature], so that [benefit]")
        score -= 0.15

    if not has_role:
        issues.append("Missing actor/role")
        suggestions.append("Specify who performs the action")
        score -= 0.10

    has_value = bool(re.search(r"\bso that\b", sl) or re.search(r"\bafin d[e']?\b", sl) or re.search(r"\bpour que\b", sl))
    if not has_value:
        issues.append("Missing business value")
        suggestions.append("Add 'so that [benefit]' clause")
        score -= 0.15

    wc = len(story.split())
    if wc > 50:
        issues.append("Story too long (>50 words)")
        suggestions.append("Keep it concise (30-40 words recommended)")
        score -= 0.10
    elif wc < 5:
        issues.append("Story too short (<5 words)")
        suggestions.append("Provide more meaningful detail")
        score -= 0.10

    vague = ["quickly", "easily", "efficiently", "fast", "user-friendly", "rapidement", "facilement", "efficacement", "simple", "intuitif"]
    found = [w for w in vague if w in sl]
    if found:
        issues.append(f"Vague terms: {', '.join(found)}")
        suggestions.append("Replace vague terms with measurable criteria")
        score -= 0.10

    return {"score": round(max(0.0, min(1.0, score)), 3), "issues": issues, "suggestions": suggestions}


def _nlp_score(story: str) -> Dict[str, Any]:
    issues: List[str] = []
    suggestions: List[str] = []
    score = 1.0
    text = story.lower()

    vague = ["quickly", "easily", "efficiently", "fast", "better", "rapidement", "facilement", "efficacement", "simple", "intuitif"]
    found = [w for w in vague if w in text]
    if found:
        issues.append(f"Ambiguous terms: {', '.join(found)}")
        suggestions.append("Replace with measurable criteria")
        score -= 0.15

    non_testable = [r"works well", r"perform(s)? better", r"improve(s)?", r"optimize(s)?", r"bonne performance", r"améliorer", r"optimiser"]
    for p in non_testable:
        if re.search(p, text):
            issues.append("Non-testable requirement detected")
            suggestions.append("Use measurable acceptance criteria (response time, success rate)")
            score -= 0.20
            break

    passive = [r"\bis (created|updated|deleted|processed)\b", r"\bare (created|updated|deleted)\b", r"\best (créé|mis à jour|supprimé)\b"]
    for p in passive:
        if re.search(p, text):
            issues.append("Passive voice detected")
            suggestions.append("Use active voice (e.g., 'user creates account')")
            score -= 0.10
            break

    return {"score": round(max(0.0, min(1.0, score)), 3), "issues": issues, "suggestions": suggestions}


_VERIFIABLE = re.compile(
    r"\b(doit|must|shall|should|will|can|peut|"
    r"display|show|affiche|montre|présente|"
    r"return|retourne|renvoie|send|envoie|receive|reçoit|"
    r"create|crée|delete|supprime|update|modifie|"
    r"validate|valide|verify|vérifie|check|contrôle|"
    r"generate|génère|select|sélectionne|"
    r"accept|accepte|reject|rejette)\b",
    re.IGNORECASE,
)

_MEASURABLE = re.compile(
    r"\b\d+\s*(ms|secondes?|seconds?|sec|minutes?|min|heures?|hours?|"
    r"caractères?|characters?|chars?|items?|%)\b|"
    r"(at least|at most|minimum|maximum|less than|more than|within|"
    r"au moins|au plus|moins de|plus de|dans un délai de)\s*\d+",
    re.IGNORECASE,
)


def _testability_score(story: str, ac_list: List[str]) -> Dict[str, Any]:
    lang = _detect_language(story)
    issues: List[str] = []
    suggestions: List[str] = []
    ac_count = len(ac_list)

    if ac_count == 0:
        return {
            "score": 0.2,
            "is_testable": False,
            "issues": ["No acceptance criteria defined" if lang == "en" else "Aucun critère d'acceptation défini"],
            "suggestions": ["Add at least 2 acceptance criteria" if lang == "en" else "Ajouter au moins 2 critères d'acceptation"],
        }

    score = 0.4
    if ac_count >= 5:
        score += 0.08
    elif ac_count >= 3:
        score += 0.05
    else:
        score += 0.01
        issues.append("Few acceptance criteria" if lang == "en" else "Peu de critères d'acceptation")
        suggestions.append("Add more criteria (3+ recommended)" if lang == "en" else "Ajouter plus de critères (3+ recommandés)")

    verifiable = sum(1 for ac in ac_list if _VERIFIABLE.search(ac))
    v_ratio = verifiable / ac_count
    if v_ratio >= 0.8:
        score += 0.20
    elif v_ratio >= 0.6:
        score += 0.15
    elif v_ratio >= 0.4:
        score += 0.08
    else:
        score += 0.03
        issues.append(f"Only {verifiable}/{ac_count} criteria are verifiable" if lang == "en" else f"Seulement {verifiable}/{ac_count} critères sont vérifiables")
        suggestions.append("Use action verbs: displays, returns, creates, validates" if lang == "en" else "Utiliser des verbes d'action : affiche, retourne, crée, valide")

    measurable = sum(1 for ac in ac_list if _MEASURABLE.search(ac))
    m_ratio = measurable / ac_count
    if m_ratio >= 0.5:
        score += 0.25
    elif m_ratio >= 0.25:
        score += 0.15
    elif measurable > 0:
        score += 0.05
    else:
        score -= 0.10
        issues.append("No measurable criteria (time, quantity, limit)" if lang == "en" else "Aucun critère mesurable")
        suggestions.append("Add measurable conditions: 'within 2s', 'minimum 6 characters'" if lang == "en" else "Ajouter des conditions mesurables : 'en moins de 2s', 'minimum 6 caractères'")

    score = round(max(0.0, min(1.0, score)), 3)
    return {
        "score": score,
        "is_testable": score >= 0.7 and ac_count >= 2 and measurable >= 1,
        "issues": issues[:3],
        "suggestions": suggestions[:3],
    }


def _ac_quality_score(ac_list: List[str]) -> float:
    if not ac_list:
        return 0.0
    testable = [ac for ac in ac_list if len(ac.split()) >= 3 or _VERIFIABLE.search(ac)]
    if not testable:
        return 0.0
    ratio = len(testable) / len(ac_list)
    detailed = [ac for ac in testable if len(ac.split()) > 6]
    bonus = min(0.2, len(detailed) / max(len(testable), 1) * 0.2)
    return round(min(1.0, ratio + bonus), 3)


def _weighted_final_score(ac_score, rule_score, nlp_score, testability_score, is_garbage, is_testable) -> float:
    if is_garbage:
        return round(min(0.3, ac_score * 0.1 + rule_score * 0.1), 3)

    # Testability is the primary differentiator — high weight ensures small
    # differences in testability_score produce meaningfully different final scores.
    if ac_score > 0:
        base = testability_score * 0.55 + ac_score * 0.25 + rule_score * 0.12 + nlp_score * 0.08
    else:
        base = testability_score * 0.65 + rule_score * 0.22 + nlp_score * 0.13

    # Modest proportional penalty instead of hard band ceilings, which caused
    # all stories in a testability range to get the exact same capped score.
    if not is_testable:
        base *= 0.90

    return round(max(0.0, min(1.0, base)), 3)


# ============================================================
# PUBLIC EVALUATORS
# ============================================================

async def extract_acceptance_criteria(
    story: str,
    existing_ac: List[str] = None,
) -> Dict[str, Any]:
    """
    Parse and clean acceptance criteria from a user story.

    Use this as a preprocessing step before scoring when AC may be
    embedded in the story text or need deduplication/cleanup.

    Returns:
        acceptance_criteria: Cleaned AC list
        count: Number of items
    """
    try:
        existing_ac = existing_ac or []

        block_pattern = re.compile(
            r"(?:acceptance criteria|critères d[''']acceptation|ac)\s*[:\-]?\s*\n"
            r"((?:\s*[-•*]\s*.+\n?)+)",
            re.IGNORECASE | re.MULTILINE,
        )
        bullet_pattern = re.compile(r"[-•*]\s*(.+)")

        extracted: List[str] = []
        for match in block_pattern.finditer(story):
            lines = bullet_pattern.findall(match.group(1))
            extracted.extend(l.strip() for l in lines if len(l.strip()) > 5)

        if not extracted and existing_ac:
            extracted = list(existing_ac)

        seen: set = set()
        result: List[str] = []
        for ac in extracted:
            ac_clean = ac.strip().lstrip("-*• ").strip()
            ac_clean = re.sub(
                r"^(?:acceptance criteria|critères d[''']acceptation)\s*[:\-]?\s*",
                "", ac_clean, flags=re.IGNORECASE,
            ).strip()
            norm = " ".join(ac_clean.lower().split())
            if not norm or norm in seen or len(ac_clean.split()) < 3 or norm in {"ok", "done", "validé"}:
                continue
            seen.add(norm)
            result.append(ac_clean)

        logger.info(f"[EVALUATOR] extract_ac: {len(result)} items")
        return {"status": "success", "acceptance_criteria": result, "count": len(result)}

    except Exception as e:
        logger.error(f"[EVALUATOR] extract_ac failed: {e}")
        return {"status": "error", "error": str(e), "acceptance_criteria": [], "count": 0}


async def score_story(
    story: str,
    acceptance_criteria: List[str] = None,
) -> Dict[str, Any]:
    """
    Score a user story for quality and testability.

    Returns:
        final_score, rule_score, nlp_score, ac_score, testability_score,
        is_testable, is_garbage, issues, suggestions
    """
    try:
        acceptance_criteria = acceptance_criteria or []
        is_garbage = _is_garbage(story)

        rule, nlp, testability = await asyncio.gather(
            asyncio.to_thread(_rule_score, story),
            asyncio.to_thread(_nlp_score, story),
            asyncio.to_thread(_testability_score, story, acceptance_criteria),
        )

        ac_sc = _ac_quality_score(acceptance_criteria)
        final_score = _weighted_final_score(
            ac_score=ac_sc,
            rule_score=rule["score"],
            nlp_score=nlp["score"],
            testability_score=testability["score"],
            is_garbage=is_garbage,
            is_testable=testability["is_testable"],
        )

        logger.info(
            f"[EVALUATOR] score={final_score:.3f} rule={rule['score']:.3f} "
            f"nlp={nlp['score']:.3f} ac={ac_sc:.3f} test={testability['score']:.3f} "
            f"testable={testability['is_testable']} garbage={is_garbage}"
        )

        return {
            "status": "success",
            "final_score": final_score,
            "rule_score": rule["score"],
            "nlp_score": nlp["score"],
            "ac_score": ac_sc,
            "testability_score": testability["score"],
            "is_testable": testability["is_testable"],
            "is_garbage": is_garbage,
            "testability_issues": testability["issues"],
            "issues": rule["issues"][:2] + nlp["issues"][:2] + testability["issues"][:2],
            "suggestions": rule["suggestions"][:2] + nlp["suggestions"][:2] + testability["suggestions"][:2],
        }

    except Exception as e:
        logger.error(f"[EVALUATOR] score_story failed: {e}", exc_info=True)
        return {
            "status": "error", "final_score": 0.0, "rule_score": 0.0,
            "nlp_score": 0.0, "ac_score": 0.0, "testability_score": 0.0,
            "is_testable": False, "is_garbage": False,
            "testability_issues": ["Scoring error"],
            "issues": [str(e)], "suggestions": [], "error": str(e),
        }


async def validate_constraints(
    original_story: str,
    improved_story: str,
    acceptance_criteria: List[str] = None,
) -> Dict[str, Any]:
    """
    Validate that the improved story respects all business constraints.

    Checks: language, actor/role, verbosity, domain drift, intent overlap, embedding similarity.

    Returns:
        is_safe, violations, similarity, language_match, role_preserved
    """
    try:
        acceptance_criteria = acceptance_criteria or []
        violations: List[str] = []

        lang_orig = _detect_language(original_story)
        lang_impr = _detect_language(improved_story)
        language_match = lang_orig == lang_impr
        if not language_match:
            violations.append(f"Language changed: {lang_orig} → {lang_impr}")

        orig_role = _extract_role(original_story)
        impr_role = _extract_role(improved_story)
        role_preserved = not orig_role or orig_role == impr_role or orig_role.lower() in impr_role.lower()
        if not role_preserved:
            violations.append(f"Actor changed: '{orig_role}' → '{impr_role}'")

        orig_wc = len(original_story.split())
        impr_wc = len(improved_story.split())
        if orig_wc > 0 and impr_wc > orig_wc * 1.8:
            violations.append(f"Story too verbose: {impr_wc} words vs {orig_wc} original (limit ×1.8)")

        orig_lower = original_story.lower()
        impr_lower = improved_story.lower()
        forbidden_added = [kw for kw in ("payment", "billing", "invoice", "analytics") if kw in impr_lower and kw not in orig_lower]
        if forbidden_added:
            violations.append(f"Domain drift — forbidden terms added: {forbidden_added}")

        orig_words = set(re.findall(r"\b\w{3,}\b", orig_lower))
        impr_words = set(re.findall(r"\b\w{3,}\b", impr_lower))
        overlap = len(orig_words & impr_words) / max(len(orig_words), 1)
        if overlap < 0.40:
            violations.append(f"Intent drift — word overlap too low: {overlap:.0%} (minimum 40%)")

        similarity = 0.0
        try:
            from app.core.embedding_cache import embed, cosine_similarity
            emb_orig, emb_impr = await asyncio.gather(embed(original_story), embed(improved_story))
            if emb_orig is not None and emb_impr is not None:
                similarity = float(cosine_similarity(emb_orig, emb_impr))
                if similarity < 0.65:
                    violations.append(f"Similarity too low: {similarity:.1%} (minimum 65%)")
        except ImportError:
            logger.warning("[EVALUATOR] Embedding import failed — skipping similarity check")
        except Exception as emb_err:
            logger.warning(f"[EVALUATOR] Embedding similarity skipped: {emb_err}")

        is_safe = len(violations) == 0
        logger.info(f"[EVALUATOR] validate: is_safe={is_safe} similarity={similarity:.3f}")
        if violations:
            logger.warning(f"[EVALUATOR] Violations: {violations}")

        return {
            "status": "success",
            "is_safe": is_safe,
            "violations": violations,
            "similarity": round(similarity, 3),
            "language_match": language_match,
            "role_preserved": role_preserved,
        }

    except Exception as e:
        logger.error(f"[EVALUATOR] validate_constraints failed: {e}")
        return {
            "status": "error", "is_safe": False,
            "violations": [f"Validation error: {str(e)}"],
            "similarity": 0.0, "language_match": True, "role_preserved": True,
            "error": str(e),
        }
