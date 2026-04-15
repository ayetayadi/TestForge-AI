
import re
import logging
import html
from typing import Dict, Union, List

from app.ai_agents_v2.user_story_refinement.utils.text_processing import detect_language

logger = logging.getLogger(__name__)


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
   
   
def compute_testability_deterministic(story: str, acceptance_criteria: List[str]) -> Dict:
    """
    Analyse DÉTERMINISTE de la testabilité.
    
    ✅ Valorise FORTEMENT la structure et la vérifiabilité
    ✅ Pénalise l'absence de mesures mais sans bloquer complètement
    ✅ Bilingue FR/EN
    """
    
    lang = detect_language(story)
    
    # ============================================================
    # Messages bilingues
    # ============================================================
    MESSAGES = {
        "fr": {
            "no_ac": "Aucun critère d'acceptation défini",
            "add_ac": "Ajouter au moins 2 critères d'acceptation",
            "few_ac": "Peu de critères d'acceptation",
            "add_more_ac": "Ajouter plus de critères (3+ recommandés)",
            "few_verifiable": "Seulement {verifiable}/{total} critères sont clairement vérifiables",
            "use_action_verbs": "Utiliser des verbes d'action : affiche, retourne, crée, valide...",
            "no_measurable": "Aucun critère mesurable : sans conditions mesurables, les tests ne peuvent pas valider le comportement",
            "add_measurable": "Ajouter des conditions mesurables : 'en moins de 2s', 'minimum 6 caractères'",
            "ambiguous_terms": "Termes ambigus dans la story: {terms}",
            "replace_ambiguous": "Remplacer les termes ambigus par des critères mesurables",
            "well_structured": "Critères bien structurés et vérifiables",
        },
        "en": {
            "no_ac": "No acceptance criteria defined",
            "add_ac": "Add at least 2 acceptance criteria",
            "few_ac": "Few acceptance criteria",
            "add_more_ac": "Add more criteria (3+ recommended)",
            "few_verifiable": "Only {verifiable}/{total} criteria are clearly verifiable",
            "use_action_verbs": "Use action verbs: displays, returns, creates, validates...",
            "no_measurable": "No measurable criteria (time, quantity, limit)",
            "add_measurable": "Add measurable conditions: 'within 2s', 'minimum 6 characters'",
            "ambiguous_terms": "Ambiguous terms in story: {terms}",
            "replace_ambiguous": "Replace ambiguous terms with measurable criteria",
            "well_structured": "Well-structured and verifiable criteria",
        }
    }
    
    msg = MESSAGES[lang]
    
    issues = []
    suggestions = []
    
    ac_count = len(acceptance_criteria)
    
    # ============================================================
    # SCORE DE BASE (commence à 0.4 pour laisser place à l'amélioration)
    # ============================================================
    score = 0.4
    
    # ============================================================
    # RÈGLE 1 : Présence d'AC (CRITIQUE)
    # ============================================================
    if ac_count == 0:
        issues.append(msg["no_ac"])
        suggestions.append(msg["add_ac"])
        score = 0.2  # Très mauvais
        return {
            "score": score,
            "is_testable": False,
            "issues": issues,
            "suggestions": suggestions,
            "details": {"ac_count": 0, "verifiable_count": 0, "measurable_count": 0, "language": lang}
        }
    
    # ============================================================
    # RÈGLE 2 : Quantité d'AC (BONUS)
    # ============================================================
    if ac_count >= 5:
        score += 0.08  # Excellent
    elif ac_count >= 3:
        score += 0.05  # Bon
    elif ac_count >= 1:
        score += 0.01  # Minimum
        issues.append(msg["few_ac"])
        suggestions.append(msg["add_more_ac"])
    
    # ============================================================
    # RÈGLE 3 : Vérifiabilité (TRÈS IMPORTANT)
    # ============================================================
    VERIFIABLE_PATTERN = re.compile(
        r"\b(doit|must|shall|should|will|can|peut|"
        r"display|show|affiche|montre|présente|present|"
        r"return|retourne|renvoie|send|envoie|receive|reçoit|"
        r"create|crée|delete|supprime|update|modifie|change|"
        r"validate|valide|verify|vérifie|check|contrôle|"
        r"génère|generate|produit|produce|"
        r"sélectionne|select|choisit|choose|"
        r"révoque|revoke|annule|cancel|"
        r"accepte|accept|rejette|reject)\b",
        re.IGNORECASE
    )
    
    verifiable_count = sum(1 for ac in acceptance_criteria if VERIFIABLE_PATTERN.search(ac))
    verifiable_ratio = verifiable_count / ac_count if ac_count > 0 else 0
    
    if verifiable_ratio >= 0.8:
        score += 0.20  # Très bonne vérifiabilité
    elif verifiable_ratio >= 0.6:
        score += 0.15  # Bonne vérifiabilité
    elif verifiable_ratio >= 0.4:
        score += 0.08  # Moyen
    else:
        score += 0.03  # Faible
        issues.append(msg["few_verifiable"].format(verifiable=verifiable_count, total=ac_count))
        suggestions.append(msg["use_action_verbs"])
    
    # ============================================================
    # RÈGLE 4 : Mesurabilité (IMPORTANT mais pas bloquant)
    # ============================================================
    MEASURABLE_PATTERN = re.compile(
        r"\b\d+\s*(secondes?|seconds?|second|sec|s)\b|"
        r"\b\d+\s*(minutes?|min|mins?)\b|"
        r"\b\d+\s*(heures?|hours?|h)\b|"
        r"\b\d+\s*(ms|millisecondes?|milliseconds?)\b|"
        r"\b\d+\s*(caractères?|characters?|chars?)\b|"
        r"\b\d+\s*(éléments?|items?|tokens?)\b|"
        r"\b\d+\s*(%|pour\s*cent|percent)\b|"
        r"\b\d+\s*(fois|times|tentatives?|attempts?)\b|"
        r"(au moins|at least|minimum|min)\s*\d+|"
        r"(au plus|at most|maximum|max)\s*\d+|"
        r"(moins de|less than|under)\s*\d+|"
        r"(plus de|more than|over)\s*\d+|"
        r"(empêche|prevents?|blocks?)|"
        r"(dans un délai de|within)\s*\d+",
        re.IGNORECASE
    )
    
    measurable_count = sum(1 for ac in acceptance_criteria if MEASURABLE_PATTERN.search(ac))
    measurable_ratio = measurable_count / ac_count if ac_count > 0 else 0
    
    if measurable_ratio >= 0.5:
        score += 0.25  # Excellent - critères mesurables
    elif measurable_ratio >= 0.25:
        score += 0.15  # Bon - quelques mesures
    elif measurable_count > 0:
        score += 0.05  # Au moins un
    else:
        # Pas de mesure = pénalité mais PAS de plafond bloquant
        issues.append(msg["no_measurable"])
        suggestions.append(msg["add_measurable"])
        score -= 0.10  # Pénalité légère (au lieu de plafonner à 0.6)
    
    # ============================================================
    # RÈGLE 5 : Structure des AC (BONUS)
    # ============================================================
    # Vérifier si les AC sont bien formés (commencent par un verbe ou "Le/La/L'")
    STRUCTURE_PATTERN = re.compile(
        r"^(Le |La |L'|Un |Une |The |A |An |"
        r"Lorsque |Quand |When |If |Si |"
        r"[A-ZÀ-Ý][a-zà-ÿ]+ (doit|must|shall|should|will|can|peut))",
        re.IGNORECASE
    )
    
    structured_count = sum(1 for ac in acceptance_criteria if STRUCTURE_PATTERN.match(ac.strip()))
    structured_ratio = structured_count / ac_count if ac_count > 0 else 0
    
    if structured_ratio >= 0.7:
        score += 0.05  # Bonus structure
    
    # ============================================================
    # RÈGLE 6 : Ambiguïté dans la story (PÉNALITÉ)
    # ============================================================
    ambiguous_terms = {
        "fr": ["rapide", "rapidement", "facile", "facilement", "simple", "simplement",
               "intuitif", "intuitive", "efficace", "correctement", "approprié", "vite"],
        "en": ["quick", "quickly", "easy", "easily", "simple", "simply",
               "intuitive", "efficient", "efficiently", "correctly", "properly", "fast"]
    }
    
    found = [term for term in ambiguous_terms[lang] if re.search(rf"\b{term}\b", story.lower())]
    
    if found:
        issues.append(msg["ambiguous_terms"].format(terms=", ".join(found[:3])))
        suggestions.append(msg["replace_ambiguous"])
        score -= 0.03 * min(len(found), 3)
    
    # ============================================================
    # FINAL
    # ============================================================
    score = round(max(0.0, min(1.0, score)), 3)
    is_testable = (
        score >= 0.7
        and ac_count >= 2
        and measurable_count >= 1
    )
    
    # Ajouter une suggestion positive si tout va bien
    if not issues and score >= 0.7:
        suggestions.insert(0, msg.get("well_structured", "Well-structured criteria"))
    
    return {
        "score": score,
        "is_testable": is_testable,
        "issues": issues[:3],
        "suggestions": suggestions[:3],
        "details": {
            "ac_count": ac_count,
            "verifiable_count": verifiable_count,
            "measurable_count": measurable_count,
            "structured_count": structured_count,
            "language": lang,
        }
    }
