# app/ai_agents/user_stories/utils/filters.py

import re
import logging
from typing import List, Tuple, Optional

from app.ai_agents.user_stories.utils.text_quality_utils import detect_language

logger = logging.getLogger(__name__)


def is_incomplete_sentence(ac: str) -> bool:
    """Vérifie si une AC est une phrase incomplète"""
    ac_stripped = ac.strip()
    if not ac_stripped:
        return True
    
    trailing_words = [
        "to", "the", "a", "an", "of", "in", "for", "and", "or", "with",
        "de", "du", "des", "le", "la", "les", "un", "une", "et",
        "ou", "à", "au", "aux", "en", "par", "sur", "vers"
    ]
    
    words = ac_stripped.split()
    if not words:
        return True
    
    last_word = words[-1].lower().rstrip(".!?,;:")
    if last_word in trailing_words:
        return True
    
    first_word = words[0]
    if len(first_word) <= 3 and first_word.isupper() and len(words) > 1:
        if first_word.lower() not in ["le", "la", "si", "if", "un"]:
            return True
    
    return False


class LanguageFilter:
    """Filtre les AC par langue"""
    
    @staticmethod
    def filter_by_language(ac_list: List[str], expected_lang: str, jira_id: str) -> List[str]:
        
        if not ac_list or not expected_lang:
            return ac_list
        
        filtered = []
        for ac in ac_list:
            ac_lang = detect_language(ac)
            if ac_lang == expected_lang:
                filtered.append(ac)
            else:
                logger.debug(f"[{jira_id}] [LANG REJECT] AC in '{ac_lang}', expected '{expected_lang}': {ac[:60]}...")
        
        if len(filtered) < len(ac_list):
            logger.info(f"[{jira_id}] [LANG FILTER] {len(ac_list) - len(filtered)} ACs rejected")
        
        return filtered


class CompletenessFilter:
    """Filtre les AC incomplètes"""
    
    @staticmethod
    def filter_complete(ac_list: List[str], jira_id: str) -> List[str]:
        complete = [a for a in ac_list if not is_incomplete_sentence(a)]
        removed = len(ac_list) - len(complete)
        if removed:
            logger.info(f"[{jira_id}] [TRUNCATION FILTER] {removed} incomplete ACs removed")
        return complete


class DriftFilter:
    """
    Filtre intelligent pour détecter les AC qui dérivent du contexte.
    
    IMPORTANT: Ce filtre est conçu pour éviter les faux positifs.
    Il ne bloque que les cas évidents de drift sémantique.
    """
    
    # ══════════════════════════════════════════════════════════════════
    # CONFIGURATION DES RÈGLES DE DRIFT
    # ══════════════════════════════════════════════════════════════════
    
    # Structure: action -> {blocked_phrases, exceptions}
    # - blocked_phrases: Phrases COMPLÈTES qui indiquent un drift (pas de mots isolés !)
    # - exceptions: Contextes où les termes "opposés" sont en fait valides
    
    DRIFT_RULES = {
        # ─────────────────────────────────────────────────────────────
        # DÉCONNEXION (ne doit pas parler de connexion)
        # ─────────────────────────────────────────────────────────────
        "logout_fr": {
            "story_keywords": ["déconnexion", "déconnecter", "se déconnecter"],
            "story_exceptions": ["connexion et déconnexion", "authentification complète"],
            "blocked_phrases": [
                "se connecter avec",
                "connexion avec des identifiants",
                "saisir un email et un mot de passe",
                "entrer ses identifiants",
                "authentification de l'utilisateur",
                "identifiants valides",
                "identifiants invalides",
                "tentative de connexion",
            ],
            "allowed_phrases": [
                "après connexion",          # Contexte temporel OK
                "session de connexion",     # Référence OK  
                "état de connexion",        # État OK
                "dernière connexion",       # Historique OK
            ],
        },
        
        # ─────────────────────────────────────────────────────────────
        # CONNEXION (ne doit pas parler de déconnexion)
        # ─────────────────────────────────────────────────────────────
        "login_fr": {
            "story_keywords": ["connexion", "se connecter", "authentification"],
            "story_exceptions": ["connexion et déconnexion", "déconnexion"],
            "blocked_phrases": [
                "bouton de déconnexion",
                "se déconnecter du système",
                "terminer la session",
                "fermer la session",
            ],
            "allowed_phrases": [
                "avant déconnexion",
                "puis déconnexion",
            ],
        },
        
        # ─────────────────────────────────────────────────────────────
        # EXPORT (ne doit pas parler d'import comme ACTION PRINCIPALE)
        # ─────────────────────────────────────────────────────────────
        "export": {
            "story_keywords": ["export", "exporter", "exportation"],
            "story_exceptions": ["import et export", "import/export", "importer et exporter"],
            "blocked_phrases": [
                # Seulement les vraies actions d'import opposées
                "importer des fichiers",
                "importer depuis",
                "importation de données",
                "charger un fichier",
                "upload de fichier",
                "récupérer depuis une source externe",
            ],
            "allowed_phrases": [
                # Contextes où "import" est OK dans une story d'export
                "importés dans",            # Résultat de l'export côté destination
                "importés avec succès",     # Confirmation
                "nombre de cas importés",   # Métrique de résultat
                "import réussi",            # Status de l'export
                "importation dans squash",  # Destination
                "importation côté",         # Côté serveur
                "confirmant l'import",      # Feedback
                "succès de l'import",       # Status
            ],
        },
        
        # ─────────────────────────────────────────────────────────────
        # IMPORT (ne doit pas parler d'export comme ACTION PRINCIPALE)
        # ─────────────────────────────────────────────────────────────
        "import": {
            "story_keywords": ["import", "importer", "importation"],
            "story_exceptions": ["import et export", "import/export", "importer et exporter"],
            "blocked_phrases": [
                "exporter vers",
                "exporter les données",
                "exportation de fichier",
                "télécharger vers",
                "envoyer vers une destination",
            ],
            "allowed_phrases": [
                "exporté depuis",
                "fichier exporté",
                "source d'export",
            ],
        },
        
        # ─────────────────────────────────────────────────────────────
        # SUPPRESSION (ne doit pas parler de création)
        # ─────────────────────────────────────────────────────────────
        "delete_fr": {
            "story_keywords": ["supprimer", "suppression", "effacer"],
            "story_exceptions": ["créer et supprimer", "gestion complète"],
            "blocked_phrases": [
                "créer un nouvel élément",
                "création de l'élément",
                "ajouter un nouveau",
                "formulaire de création",
            ],
            "allowed_phrases": [
                "après création",
                "depuis sa création",
                "créé précédemment",
            ],
        },
        
        # ─────────────────────────────────────────────────────────────
        # CRÉATION (ne doit pas parler de suppression)
        # ─────────────────────────────────────────────────────────────
        "create_fr": {
            "story_keywords": ["créer", "création", "ajouter", "nouveau"],
            "story_exceptions": ["créer et supprimer", "gestion complète"],
            "blocked_phrases": [
                "supprimer l'élément",
                "suppression de l'élément",
                "effacer les données",
                "confirmer la suppression",
            ],
            "allowed_phrases": [
                "remplacer suppression",
                "annuler suppression",
            ],
        },
        
        # ─────────────────────────────────────────────────────────────
        # ENGLISH LOGOUT
        # ─────────────────────────────────────────────────────────────
        "logout_en": {
            "story_keywords": ["logout", "log out", "sign out", "disconnect"],
            "story_exceptions": ["login and logout", "sign in and sign out"],
            "blocked_phrases": [
                "log in with",
                "login with credentials",
                "enter email and password",
                "authentication attempt",
                "valid credentials",
                "invalid credentials",
            ],
            "allowed_phrases": [
                "after login",
                "previous login",
                "login session",
            ],
        },
        
        # ─────────────────────────────────────────────────────────────
        # ENGLISH CREATE / DELETE
        # ─────────────────────────────────────────────────────────────
        "delete_en": {
            "story_keywords": ["delete", "remove", "deletion"],
            "story_exceptions": ["create and delete", "full management"],
            "blocked_phrases": [
                "create a new",
                "creation of",
                "add a new",
                "creation form",
            ],
            "allowed_phrases": [
                "after creation",
                "previously created",
            ],
        },
        
        "create_en": {
            "story_keywords": ["create", "creation", "add new"],
            "story_exceptions": ["create and delete", "full management"],
            "blocked_phrases": [
                "delete the",
                "deletion of",
                "remove the",
                "confirm deletion",
            ],
            "allowed_phrases": [
                "replace deletion",
                "undo deletion",
            ],
        },
    }
    
    @classmethod
    def _detect_story_action(cls, story_lower: str) -> Optional[str]:
        """Détecte quelle règle de drift s'applique à cette story."""
        for rule_name, rule_config in cls.DRIFT_RULES.items():
            # Vérifier si la story contient les keywords
            if any(kw in story_lower for kw in rule_config["story_keywords"]):
                # Vérifier les exceptions (story couvre plusieurs actions)
                if any(exc in story_lower for exc in rule_config["story_exceptions"]):
                    continue
                return rule_name
        return None
    
    @classmethod
    def _is_drifted(cls, ac_lower: str, rule_config: dict) -> Tuple[bool, Optional[str]]:
        """
        Vérifie si un AC drift selon la règle donnée.
        
        Returns:
            (is_drifted, reason)
        """
        # D'abord vérifier les phrases autorisées (exceptions)
        for allowed in rule_config.get("allowed_phrases", []):
            if allowed in ac_lower:
                return False, None
        
        # Ensuite vérifier les phrases bloquées
        for blocked in rule_config.get("blocked_phrases", []):
            if blocked in ac_lower:
                return True, f"contains '{blocked}'"
        
        return False, None
    
    @classmethod
    def filter_drifted_ac(cls, ac_list: List[str], story: str, jira_id: str) -> List[str]:
        """
        Filtre les AC qui dérivent du contexte de la story.
        
        Cette méthode est CONSERVATRICE : elle ne supprime que les cas
        évidents de drift pour éviter les faux positifs.
        """
        if not ac_list:
            return ac_list
        
        story_lower = story.lower()
        
        # Détecter quelle règle s'applique
        rule_name = cls._detect_story_action(story_lower)
        
        if not rule_name:
            # Pas de règle applicable, garder tous les AC
            return ac_list
        
        rule_config = cls.DRIFT_RULES[rule_name]
        
        filtered = []
        removed = []
        
        for ac in ac_list:
            ac_lower = ac.lower()
            is_drifted, reason = cls._is_drifted(ac_lower, rule_config)
            
            if is_drifted:
                removed.append((ac, reason))
                logger.warning(
                    f"[{jira_id}] [AC DRIFT] Rule '{rule_name}': {ac[:60]}... ({reason})"
                )
            else:
                filtered.append(ac)
        
        if removed:
            logger.info(
                f"[{jira_id}] [AC DRIFT SUMMARY] Removed {len(removed)}/{len(ac_list)} ACs"
            )
        
        return filtered