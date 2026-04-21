import asyncio
import re
import logging
import html
from typing import Dict, Union, List

logger = logging.getLogger(__name__)

# ============================================================
# IMPORT EXTERNAL SERVICES
# ============================================================
from app.core.embedding_cache import cosine_similarity, embed


def sanitize_story(raw: Union[str, List]) -> str:
    """Nettoie une story brute"""
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


async def compare_similarity(story1: str, story2: str) -> float:
    """
    Compares similarity between two stories using embeddings.
    
    CALLED DIRECTLY (not a tool).
    
    Uses cosine similarity on embeddings to determine
    how different two stories are.
    
    Args:
        story1: Original story text
        story2: New/improved story text
        
    Returns:
        Similarity score (0-1)
        - 1.0 = identical
        - 0.0 = completely different
        - 0.65+ = acceptable (similar intent preserved)
    
    Example:
        >>> similarity = compare_similarity(
        ...     "As a user, I want to login",
        ...     "As a user, I want to login with email"
        ... )
        >>> similarity
        0.87
    """
    
    try:
        # Validate inputs
        if not story1 or not story2:
            logger.warning("Empty story provided to compare_similarity")
            return 0.5  # Default to neutral
        
        # Generate embeddings
        emb1, emb2 = await asyncio.gather(
            embed(story1),
            embed(story2)
        )
        
        # Check if embeddings are valid
        if emb1 is None or emb2 is None:
            logger.warning("Failed to generate embeddings")
            return 0.5
        
        # Calculate similarity
        similarity = cosine_similarity(emb1, emb2)
        
        logger.debug(f"Similarity calculated: {similarity:.3f}")
        
        return float(similarity)
    
    except Exception as e:
        logger.error(f"Similarity comparison failed: {e}")
        return 0.5  # Default to neutral on error


def clean_story_text(story: str) -> str:
    """
    Cleans and sanitizes story text.
    
    CALLED DIRECTLY (not a tool).
    
    Removes:
    - Extra whitespace
    - Invalid characters
    - Formatting issues
    
    Args:
        story: Raw story text
        
    Returns:
        Cleaned story text
        - Preserves original if sanitization fails
        - Removes trailing/leading whitespace
        - Normalizes internal spacing
    
    Example:
        >>> clean_story_text("   As a user,  I want to login   ")
        "As a user, I want to login"
    """
    
    try:
        # Use external sanitizer
        sanitized = sanitize_story(story)
        
        # Validate result
        if sanitized and sanitized.strip():
            logger.debug(f"Story cleaned ({len(story)} → {len(sanitized)} chars)")
            return sanitized
        
        # Fallback to original if sanitization failed
        return story.strip()
    
    except Exception as e:
        logger.error(f"Story sanitization failed: {e}")
        return story.strip()  # Return original but stripped


async def is_improvement_valid(
    original: str,
    improved: str,
    min_similarity: float = 0.65
) -> bool:
    """
    Checks if improved story is valid (not too different from original).
    
    CALLED DIRECTLY (not a tool).
    
    Ensures improvement:
    - Preserves original intent
    - Doesn't deviate too much
    - Maintains similarity threshold
    
    Args:
        original: Original story
        improved: Improved/new story
        min_similarity: Minimum required similarity threshold (default 0.65 = 65%)
        
    Returns:
        True if improvement is valid
        False if story changed too much (similarity < threshold)
    
    Thresholds:
        - 0.9+ = Very similar (minor improvements)
        - 0.7-0.9 = Similar (good improvements)
        - 0.65-0.7 = Acceptable (noticeable improvements)
        - < 0.65 = Too different (rejected)
    
    Example:
        >>> is_improvement_valid(
        ...     "As a user, I want to login",
        ...     "As a user, I want to login with email and password",
        ...     min_similarity=0.65
        ... )
        True
    """
    
    try:
        # Calculate similarity
        similarity = await compare_similarity(original, improved)
        
        # Check threshold
        is_valid = similarity >= min_similarity
        
        if is_valid:
            logger.info(f"✓ Improvement valid (similarity={similarity:.3f} >= {min_similarity})")
        else:
            logger.warning(
                f"✗ Improvement too different "
                f"(similarity={similarity:.3f} < {min_similarity})"
            )
        
        return is_valid
    
    except Exception as e:
        logger.error(f"Validity check failed: {e}")
        return True  # Default to valid on error (safe default)


def extract_actor_from_story(story: str) -> str:
    """
    Extract the actor/role from user story.
    
    CALLED DIRECTLY (not a tool).
    
    Never invents - only extracts what's already there.
    
    Supports:
    - English: "As a [role]" or "As an [role]"
    - French: "En tant que [role]" or "En tant qu'[role]"
    - Spanish: "Como [role]"
    
    Args:
        story: User story text
        
    Returns:
        Actor/role string or empty if not found
        - Returns exactly what's between "as a" and next comma/verb
        - Never modifies or expands the role
    
    Example:
        >>> extract_actor_from_story("As a user, I want to login")
        "user"
        
        >>> extract_actor_from_story("As an admin, I want to delete users")
        "admin"
        
        >>> extract_actor_from_story("En tant qu'utilisateur, je veux me connecter")
        "utilisateur"
    """
    
    try:
        # Validate input
        if not story:
            logger.warning("Empty story provided to extract_actor_from_story")
            return ""
        
        story_lower = story.lower()
        
        # Pattern 1: English "As a/an [role]"
        match_en = re.search(
            r"(?:as an?|as an?)\s+([^,\n]+?)(?:,|\s+i want|\s+I want|$)",
            story_lower
        )
        if match_en:
            actor = match_en.group(1).strip()
            logger.debug(f"Extracted English actor: {actor}")
            return actor
        
        # Pattern 2: French "En tant que/qu' [role]"
        match_fr = re.search(
            r"(?:en tant qu[e']?|en tant qu[e']?)\s+([^,\n]+?)(?:,|\s+je veux|\s+Je veux|$)",
            story_lower
        )
        if match_fr:
            actor = match_fr.group(1).strip()
            logger.debug(f"Extracted French actor: {actor}")
            return actor
        
        # Pattern 3: Spanish "Como [role]"
        match_es = re.search(
            r"(?:como|como)\s+un?\s+([^,\n]+?)(?:,|\s+quiero|\s+Quiero|$)",
            story_lower
        )
        if match_es:
            actor = match_es.group(1).strip()
            logger.debug(f"Extracted Spanish actor: {actor}")
            return actor
        
        # Fallback: Look for common role keywords
        common_roles = [
            "administrateur", "admin", "administrator",
            "utilisateur", "user",
            "customer", "client",
            "manager", "gestionnaire",
            "developer", "développeur",
        ]
        
        for role in common_roles:
            if role in story_lower:
                logger.debug(f"Extracted fallback actor: {role}")
                return role
        
        logger.warning("Could not extract actor from story")
        return ""
    
    except Exception as e:
        logger.error(f"Actor extraction failed: {e}")
        return ""


def verify_language_consistency(original: str, improved: str) -> bool:
    """
    Verify that output language matches input language.
    
    CALLED DIRECTLY (not a tool).
    
    Ensures:
    - Input language = Output language
    - No language mixing
    - Consistent throughout output
    
    Args:
        original: Original story (input)
        improved: Improved story (output)
        
    Returns:
        True if languages match
        False if language mismatch
    
    Example:
        >>> verify_language_consistency(
        ...     "As a user, I want to login",
        ...     "As a user, I want to login with email"
        ... )
        True  # Both English
        
        >>> verify_language_consistency(
        ...     "As a user, I want to login",
        ...     "En tant qu'utilisateur, je veux me connecter"
        ... )
        False  # English → French mismatch
    """
    
    try:
        # Detect languages
        lang_original = detect_language(original)
        lang_improved = detect_language(improved)
        
        # Check consistency
        is_consistent = lang_original == lang_improved
        
        if is_consistent:
            logger.info(f"✓ Language consistent: {lang_original}")
        else:
            logger.warning(f"✗ Language mismatch: {lang_original} → {lang_improved}")
        
        return is_consistent
    
    except Exception as e:
        logger.error(f"Language consistency check failed: {e}")
        return True  # Default to ok on error


def verify_role_preserved(original: str, improved: str) -> bool:
    """
    Verify that actor/role is preserved and not invented.
    
    CALLED DIRECTLY (not a tool).
    
    Ensures:
    - Original actor is maintained
    - No new actors invented
    - Actor only expanded if necessary for clarity
    
    Args:
        original: Original story
        improved: Improved story
        
    Returns:
        True if role is preserved or kept consistent
        False if role was changed/invented
    
    Example:
        >>> verify_role_preserved(
        ...     "As a user, I want to login",
        ...     "As a user, I want to login with email and password"
        ... )
        True  # Role preserved (user → user)
        
        >>> verify_role_preserved(
        ...     "As a user, I want to login",
        ...     "As an authenticated user, I want to login"
        ... )
        False  # Role changed/invented (user → authenticated user)
    """
    
    try:
        # Extract actors
        original_actor = extract_actor_from_story(original)
        improved_actor = extract_actor_from_story(improved)
        
        # If no actor in original, no constraint
        if not original_actor:
            logger.info("✓ No actor to preserve (original empty)")
            return True
        
        # Check if actor is preserved
        # - Exact match
        # - Or original actor is contained in improved actor
        is_preserved = (
            improved_actor == original_actor or
            (original_actor.lower() in improved_actor.lower() and len(improved_actor) <= len(original_actor) * 1.5)
        )
        
        if is_preserved:
            logger.info(f"✓ Role preserved: {original_actor} → {improved_actor}")
        else:
            logger.warning(f"✗ Role changed: {original_actor} → {improved_actor}")
        
        return is_preserved
    
    except Exception as e:
        logger.error(f"Role preservation check failed: {e}")
        return True  # Default to ok on error


def detect_language(text: str) -> str:
    text_lower = text.lower()

    # Tier 1: User story patterns (strongest signal)
    fr_story = ["en tant que", "je veux", "afin de", "pour que"]
    en_story = ["as a", "i want", "so that"]

    if any(w in text_lower for w in fr_story):
        return "fr"
    if any(w in text_lower for w in en_story):
        return "en"

    # Tier 2: General vocabulary (for ACs, descriptions, etc.)
    fr_general = [
        "le système", "lorsque", "lorsqu'", "l'utilisateur",
        "affiche", "doit", "permet", "génère",
        "un message", "une erreur", "des cas",
        "d'erreur", "d'export", "l'export",
        "succès", "échoue", "vérifie",
        "la base de données", "le serveur",
        "les données", "le formulaire",
        "n'est pas", "ne peut pas",
    ]
    en_general = [
        "the system", "when the", "the user",
        "displays", "should", "allows", "generates",
        "a message", "an error",
        "successfully", "fails",
        "the database", "the server",
        "the data", "the form",
        "does not", "cannot",
    ]

    fr_hits = sum(1 for w in fr_general if w in text_lower)
    en_hits = sum(1 for w in en_general if w in text_lower)

    if fr_hits > en_hits:
        return "fr"
    if en_hits > fr_hits:
        return "en"

    # Tier 3: Character-level heuristic (French diacritics)
    fr_chars = sum(1 for c in text if c in "àâçéèêëîïôûùüÿœæ")
    if fr_chars >= 2:
        return "fr"

    return "en"

def tokenize(text: str) -> set:
    text = re.sub(r"[^\w\s]", "", text.lower())
    words = text.split()

    stopwords = {
        "le", "la", "les", "de", "des", "du",
        "un", "une", "et", "ou",
        "the", "a", "an", "and", "or", "to"
    }

    return {w for w in words if w not in stopwords and len(w) > 2}


def shares_keywords(story: str, ac: str) -> bool:
    story_words = tokenize(story)
    ac_words = tokenize(ac)

    common = story_words.intersection(ac_words)

    return len(common) >= 1 
