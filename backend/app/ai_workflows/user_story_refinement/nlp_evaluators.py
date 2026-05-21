"""
NLP-based evaluators — replace regex checks with spaCy + embeddings.

Drop-in replacements for the regex functions in evaluators.py:
  - detect_language_nlp          → replaces _detect_language()
  - detect_passive_voice_nlp     → replaces passive regex in _semantic_clarity_score()
  - detect_vague_terms_nlp       → replaces VAGUE_TERMS list check
  - detect_action_verbs_nlp      → replaces _VERIFIABLE regex in _testability_score()
  - extract_actor_nlp            → replaces extract_actor_from_story()
  - score_ac_coherence_nlp       → NEW: semantic coherence story ↔ AC (no regex equivalent)
"""

import asyncio
import logging
from functools import lru_cache
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


# ============================================================
# SPACY MODEL LOADER (lazy, one instance per language)
# ============================================================

@lru_cache(maxsize=2)
def _get_spacy_model(lang: str):
    """Load spaCy model once and cache it. Falls back to None on ImportError."""
    try:
        import spacy
        model_name = "fr_core_news_sm" if lang == "fr" else "en_core_web_sm"
        nlp = spacy.load(model_name, disable=["ner"])  # ner not needed for most checks
        logger.info(f"[NLP] spaCy model loaded: {model_name}")
        return nlp
    except Exception as e:
        logger.warning(f"[NLP] spaCy model unavailable ({lang}): {e}")
        return None


def _get_nlp(text: str):
    """Auto-detect language and return the right spaCy model."""
    from app.ai_workflows.user_story_refinement.utils.text_processing import detect_language
    lang = detect_language(text)
    return _get_spacy_model(lang), lang


# ============================================================
# 1. LANGUAGE DETECTION — replaces _detect_language()
# ============================================================

def detect_language_nlp(text: str) -> str:
    """
    Detect language using langdetect (statistical model) instead of keyword list.
    Falls back to the rule-based detector on error.
    """
    try:
        from langdetect import detect
        detected = detect(text)
        # langdetect returns BCP-47 codes; normalise to our two values
        return "fr" if detected.startswith("fr") else "en"
    except Exception:
        # Fallback: rule-based
        from app.ai_workflows.user_story_refinement.utils.text_processing import detect_language
        return detect_language(text)


# ============================================================
# 2. PASSIVE VOICE — replaces passive regex in _semantic_clarity_score()
# ============================================================

def detect_passive_voice_nlp(text: str) -> bool:
    """
    Detect passive voice using spaCy dependency parsing.

    spaCy marks passive subjects with dep_="nsubjpass" (EN) or "nsubj:pass" (FR).
    Falls back to regex on model unavailability.
    """
    nlp_model, lang = _get_nlp(text)

    if nlp_model is None:
        # Regex fallback
        import re
        patterns = [
            r"\bis (created|updated|deleted|processed)\b",
            r"\bare (created|updated|deleted)\b",
            r"\best (créé|mis à jour|supprimé)\b",
        ]
        return any(re.search(p, text.lower()) for p in patterns)

    doc = nlp_model(text)
    for token in doc:
        if token.dep_ in ("nsubjpass", "nsubj:pass"):
            return True
    return False


# ============================================================
# 3. VAGUE TERMS — replaces VAGUE_TERMS word-list check
# ============================================================

# Seed embeddings for "vagueness" — pre-defined anchor terms
_VAGUE_ANCHORS_EN = ["quickly", "easily", "efficiently", "better", "intuitive", "seamless"]
_VAGUE_ANCHORS_FR = ["rapidement", "facilement", "efficacement", "intuitif", "fluide"]

async def detect_vague_terms_nlp(text: str) -> List[str]:
    """
    Detect vague terms using embedding similarity to known vague anchors.
    A word is flagged as vague if its cosine similarity to any anchor >= 0.72.

    Falls back to the static word list on error.
    """
    try:
        from app.core.embedding_cache import embed, cosine_similarity

        lang = detect_language_nlp(text)
        anchors = _VAGUE_ANCHORS_EN if lang == "en" else _VAGUE_ANCHORS_FR

        words = list({w for w in text.lower().split() if len(w) > 4})
        if not words:
            return []

        # Embed all words + anchors in parallel
        all_texts = words + anchors
        embeddings = await asyncio.gather(*[embed(t) for t in all_texts])

        word_embs = embeddings[:len(words)]
        anchor_embs = embeddings[len(words):]

        vague_found = []
        for i, (word, w_emb) in enumerate(zip(words, word_embs)):
            if w_emb is None:
                continue
            for a_emb in anchor_embs:
                if a_emb is None:
                    continue
                if cosine_similarity(w_emb, a_emb) >= 0.72:
                    vague_found.append(word)
                    break  # one match per word is enough

        return vague_found

    except Exception as e:
        logger.warning(f"[NLP] detect_vague_terms_nlp fallback: {e}")
        # Static list fallback
        from app.ai_workflows.user_story_refinement.evaluators import VAGUE_TERMS
        return [w for w in VAGUE_TERMS if w in text.lower()]


# ============================================================
# 4. ACTION VERBS IN AC — replaces _VERIFIABLE regex
# ============================================================

def detect_action_verbs_nlp(text: str) -> bool:
    """
    Check if a text contains action verbs using spaCy POS tagging.
    Returns True if at least one VERB token is found.

    More reliable than the regex list because it handles conjugations,
    compound tenses, and language variations automatically.
    Falls back to regex on model unavailability.
    """
    nlp_model, _ = _get_nlp(text)

    if nlp_model is None:
        # Regex fallback
        from app.ai_workflows.user_story_refinement.evaluators import _VERIFIABLE
        return bool(_VERIFIABLE.search(text))

    doc = nlp_model(text)
    for token in doc:
        # VERB = main verb, AUX = auxiliary (must, should, doit…)
        if token.pos_ in ("VERB", "AUX") and not token.is_stop:
            return True
    return False


def count_action_verbs_nlp(ac_list: List[str]) -> int:
    """Count how many AC items contain at least one action verb."""
    return sum(1 for ac in ac_list if detect_action_verbs_nlp(ac))


# ============================================================
# 5. ACTOR EXTRACTION — replaces extract_actor_from_story()
# ============================================================

def extract_actor_nlp(text: str) -> str:
    """
    Extract the actor/role using spaCy dependency parsing.

    Looks for the subject (nsubj) of the root verb, which is the actor
    in an active user story. Falls back to the regex extractor.
    """
    # Try spaCy first — load with NER enabled for this function
    try:
        import spacy
        from app.ai_workflows.user_story_refinement.utils.text_processing import detect_language
        lang = detect_language(text)
        model_name = "fr_core_news_sm" if lang == "fr" else "en_core_web_sm"
        nlp_model = spacy.load(model_name)
        doc = nlp_model(text)

        # Look for subject of root verb
        for token in doc:
            if token.dep_ in ("nsubj", "nsubj:pass") and token.head.dep_ == "ROOT":
                # Return the full noun phrase (e.g. "admin user" not just "user")
                subtree = [t.text for t in token.subtree if not t.is_punct]
                return " ".join(subtree).strip()

    except Exception as e:
        logger.debug(f"[NLP] extract_actor_nlp spaCy failed: {e}")

    # Fallback to regex extractor
    from app.ai_workflows.user_story_refinement.utils.text_processing import extract_actor_from_story
    return extract_actor_from_story(text)


# ============================================================
# 6. STORY ↔ AC COHERENCE — new NLP score, no regex equivalent
# ============================================================

async def score_ac_coherence_nlp(story: str, ac_list: List[str]) -> Dict[str, Any]:
    """
    Measure semantic coherence between the story and each AC using embeddings.

    An AC that is semantically far from the story (cosine < 0.35) is likely
    off-topic or belongs to another story.

    Returns a score in [0, 1] and flags low-coherence AC items.
    """
    if not ac_list:
        return {"score": 0.5, "issues": [], "suggestions": [], "low_coherence_ac": []}

    try:
        from app.core.embedding_cache import embed, cosine_similarity

        story_emb, *ac_embs = await asyncio.gather(
            embed(story),
            *[embed(ac) for ac in ac_list],
        )

        similarities = []
        low_coherence = []
        for ac, ac_emb in zip(ac_list, ac_embs):
            if ac_emb is None or story_emb is None:
                similarities.append(0.5)
                continue
            sim = cosine_similarity(story_emb, ac_emb)
            similarities.append(sim)
            if sim < 0.35:
                low_coherence.append(ac[:60])

        avg_sim = sum(similarities) / len(similarities) if similarities else 0.5
        # Scale: cosine rarely reaches 1.0 in practice, ×1.25 brings it closer to [0,1]
        score = round(min(1.0, avg_sim * 1.25), 3)

        issues = []
        suggestions = []
        if low_coherence:
            issues.append(f"{len(low_coherence)} AC sémantiquement éloigné(s) de la story")
            suggestions.append("Vérifier que chaque AC se rapporte à la fonctionnalité décrite")

        return {
            "score": score,
            "issues": issues,
            "suggestions": suggestions,
            "low_coherence_ac": low_coherence,
        }

    except Exception as e:
        logger.warning(f"[NLP] score_ac_coherence_nlp failed: {e}")
        return {"score": 0.5, "issues": [], "suggestions": [], "low_coherence_ac": []}
