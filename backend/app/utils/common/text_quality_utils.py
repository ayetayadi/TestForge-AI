import re

def is_testable_ac(ac: str, strict: bool = True) -> bool:

    if not ac or len(ac.strip()) < 10:
        return False

    ac_lower = ac.lower()

    bad_patterns = [
        "some", "something",
        "desired outcome",
        "fonctionne correctement",
        "works correctly"
    ]
    if any(p in ac_lower for p in bad_patterns):
        return False

    if strict:
        # Strict mode: must be a real sentence (8+ words)
        if len(ac.split()) < 8:
            return False

        observable_keywords = [
            "affiche", "erreur", "message", "visible",
            "créé", "supprimé", "envoyé", "reçu",
            "graphique", "filtre", "export", "mise à jour",
            "displayed", "error", "message", "visible",
            "created", "deleted", "sent", "received",
            "graph", "filter", "export", "updated",
            "lorsque", "when", "si", "if", "alors", "then",
        ]

        return any(k in ac_lower for k in observable_keywords)
    else:
        # Lenient mode: accept short topic-style ACs (3+ words)
        if len(ac.split()) < 3:
            return False
        return True


def is_testable_ac_strict(ac: str) -> bool:
    """Strict mode — for LLM-generated ACs."""
    return is_testable_ac(ac, strict=True)


def is_testable_ac_lenient(ac: str) -> bool:
    """Lenient mode — for existing Jira ACs."""
    return is_testable_ac(ac, strict=False)


def deduplicate_ac(ac_list):
    seen = set()
    result = []

    for ac in ac_list:
        key = re.sub(r"\s+", " ", ac.lower().strip())

        if key not in seen:
            seen.add(key)
            result.append(ac.strip())

    return result

def normalize_list(items):
    result = []

    for i in items:
        if isinstance(i, dict):
            value = list(i.values())[0]
            if value:
                result.append(str(value))
        elif i:
            result.append(str(i))

    return result

def clean_raw_story(story: str) -> str:
    return re.split(
        r"(critères d['']?acceptation|acceptance criteria)",
        story,
        flags=re.IGNORECASE,
    )[0].strip()

def clean_story_output(text: str) -> str:

    text = re.sub(
        r"(critères d['']?acceptation|acceptance criteria).*",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    lines = text.split("\n")
    clean_lines = []

    for line in lines:
        if re.search(r"(critères|acceptance)", line, re.IGNORECASE):
            continue
        clean_lines.append(line.strip())

    text = " ".join(clean_lines)

    text = re.sub(
        r"(en tant qu['e]? [^,]+)( je veux)",
        r"\1, je veux",
        text,
        flags=re.IGNORECASE
    )

    return text.strip()

def escape_braces(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")

def detect_language(text: str) -> str:
    """
    Detect whether text is French or English.
    
    FIX: The old version only checked for user-story keywords 
    ("en tant que", "je veux", "as a", "i want"). Acceptance criteria 
    like "Le système affiche un message d'erreur lorsque..." contain 
    none of these → defaulted to English → got rejected by the language 
    filter even though they're perfectly valid French.
    
    New approach: Three-tier detection.
    1. Check user-story patterns (highest confidence)
    2. Check general French/English vocabulary (AC sentences, descriptions)
    3. Default to "en" only if no signal found
    """
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


def validate_ac(original_story: str, ac_list: list) -> list:
    if not ac_list:
        return []

    valid = []

    for ac in ac_list:
        if not is_testable_ac(ac):
            continue

        if not shares_keywords(original_story, ac):
            continue

        valid.append(ac.strip())

    if not valid:
        return ac_list[:3]

    return valid[:5]


def is_more_precise(ac1: str, ac2: str) -> bool:
    return len(ac1) > len(ac2)

def contains_new_constraints(ac):
    keywords = [
        "minimum", "max", "tentative", "caractère",
        "limit", "retry", "attempt", "length"
    ]
    return any(k in ac.lower() for k in keywords)

def normalize(s: str) -> str:
    return " ".join((s or "").lower().split())


def is_garbage_story(story: str) -> bool:
    story = story.lower()
    bad_patterns = [
        "specific action",
        "desired outcome",
        "some data",
        "something",
    ]
    if len(set(story.split())) < 5:
        generic_patterns = [
            "manage data", "handle data", "process data",
            "system data", "perform action",
        ]
        if any(p in story for p in generic_patterns):
            return True

    if any(p in story for p in bad_patterns):
        return True

    if len(story.split()) < 6:
        return True

    return False