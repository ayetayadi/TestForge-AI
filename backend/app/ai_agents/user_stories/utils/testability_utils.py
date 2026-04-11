import re

# =========================
# CONSTANTS
# =========================

TESTABILITY_THRESHOLD = 0.6

# Patterns qui indiquent une condition vérifiable
VERIFIABLE_PATTERNS = [
    r"(doit|should|must|shall)",
    r"(affiche|displays?|shows?|montre)",
    r"(retourne|returns?|renvoie)",
    r"(envoie|sends?|reçoit|receives?)",
    r"(redirige|redirects?|navigue|navigates?)",
    r"(crée|creates?|supprime|deletes?|modifie|updates?)",
    r"(active|désactive|enables?|disables?)",
    r"(bloque|blocks?|autorise|allows?)",

    # Given / When / Then
    r"(given|when|then|étant donné|quand|alors)",

    # Conditions
    r"(si|if|lorsque|when).*?(alors|then|,)",

    # États
    r"(est|is|are|devient|becomes|reste|remains)",
    r"(visible|hidden|caché|enabled|disabled|actif|inactif)",
]

# Patterns mesurables
MEASURABLE_PATTERNS = [
    r"\b\d+\s*(secondes?|seconds?|ms|minutes?|min)",
    r"\b\d+\s*(caractères?|characters?|chars?)",
    r"\b\d+\s*(%|pour\s*cent|percent)",
    r"(au moins|au plus|at least|at most|minimum|maximum|min|max)\s*\d+",
    r"(moins de|plus de|less than|more than|under|over)\s*\d+",
    r"entre\s*\d+\s*et\s*\d+",
    r"\b\d+\s*(fois|times|attempts?|tentatives?|essais?)",
]

# Ambiguïté
AMBIGUOUS_TERMS = [
    r"\b(rapide|rapidement|quickly|fast)\b",
    r"\b(facile|facilement|easily|easy)\b",
    r"\b(simple|simplement|simply)\b",
    r"\b(correctement|correctly|properly)\b",
    r"\b(intuiti[fv]e?|intuitivement|intuitively)\b",
    r"\b(efficace|efficiently|efficient)\b",
    r"\b(bonne?|good|well)\b",
    r"\b(claire?|clearly|clear)\b",
    r"\b(assez|enough|suffisant)\b",
    r"\b(appropriée?|appropriate)\b",
]


# =========================
# HELPERS
# =========================

def count_pattern_matches(text: str, patterns: list) -> int:
    return sum(1 for p in patterns if re.search(p, text.lower()))


def has_verifiable_condition(text: str) -> bool:
    return count_pattern_matches(text, VERIFIABLE_PATTERNS) > 0


def has_measurable_condition(text: str) -> bool:
    return count_pattern_matches(text, MEASURABLE_PATTERNS) > 0


def detect_ambiguity(text: str) -> list:
    found = []
    for pattern in AMBIGUOUS_TERMS:
        match = re.search(pattern, text.lower())
        if match:
            found.append(match.group())
    return found


def analyze_acceptance_criteria(ac_list: list) -> dict:
    total = len(ac_list)
    if total == 0:
        return {
            "total": 0,
            "verifiable": 0,
            "measurable": 0,
            "ambiguous": 0,
            "ratio_verifiable": 0
        }

    verifiable = sum(1 for ac in ac_list if has_verifiable_condition(ac))
    measurable = sum(1 for ac in ac_list if has_measurable_condition(ac))
    ambiguous = sum(1 for ac in ac_list if detect_ambiguity(ac))

    return {
        "total": total,
        "verifiable": verifiable,
        "measurable": measurable,
        "ambiguous": ambiguous,
        "ratio_verifiable": verifiable / total
    }


# =========================
# MAIN FUNCTION
# =========================

def compute_testability(story: str, acceptance_criteria: list) -> dict:
    issues = []
    score = 1.0

    # =========================
    # ANALYSE
    # =========================

    ac_analysis = analyze_acceptance_criteria(acceptance_criteria)
    story_ambiguity = detect_ambiguity(story)
    story_has_verifiable = has_verifiable_condition(story)

    # =========================
    # RÈGLE 1 : AC présents
    # =========================

    if ac_analysis["total"] == 0:
        issues.append("Aucun critère d'acceptation défini")
        score -= 0.4
    elif ac_analysis["total"] < 2:
        issues.append("Peu de critères d'acceptation (recommandé: 2+)")
        score -= 0.1

    # =========================
    # RÈGLE 2 : Vérifiabilité
    # =========================

    if ac_analysis["total"] > 0:
        if ac_analysis["ratio_verifiable"] < 0.5:
            issues.append(
                f"Seulement {ac_analysis['verifiable']}/{ac_analysis['total']} "
                "critères sont clairement vérifiables"
            )
            score -= 0.3
        elif ac_analysis["ratio_verifiable"] < 0.8:
            score -= 0.1

    # =========================
    # RÈGLE 3 : Ambiguïté
    # =========================

    if story_ambiguity:
        issues.append(f"Termes ambigus dans la story: {', '.join(story_ambiguity)}")
        score -= 0.15

    if ac_analysis["ambiguous"] > 0:
        issues.append(
            f"{ac_analysis['ambiguous']} critère(s) contiennent des termes ambigus"
        )
        score -= 0.15

    # =========================
    # RÈGLE 4 : MESURABILITÉ CRITIQUE
    # =========================
    
    if ac_analysis["total"] > 0:
        if ac_analysis["measurable"] == 0:
            issues.append("Aucun critère mesurable (temps, limite, quantité...)")
            
            return {
                "score": 0.4,
                "is_testable": False,
                "issues": issues,
                "details": {
                    "acceptance_criteria": ac_analysis,
                    "story_has_verifiable_condition": story_has_verifiable,
                    "story_ambiguous_terms": story_ambiguity
                },
            }

    # =========================
    # BONUS : Mesures
    # =========================

    if ac_analysis["measurable"] > 0:
        score += 0.1 * min(ac_analysis["measurable"] / ac_analysis["total"], 1)

    # =========================
    # FINAL
    # =========================

    score = round(max(0, min(score, 1.0)), 2)

    return {
        "score": score,
        "is_testable": score >= TESTABILITY_THRESHOLD,
        "issues": issues,
        "details": {
            "acceptance_criteria": ac_analysis,
            "story_has_verifiable_condition": story_has_verifiable,
            "story_ambiguous_terms": story_ambiguity
        },
    }